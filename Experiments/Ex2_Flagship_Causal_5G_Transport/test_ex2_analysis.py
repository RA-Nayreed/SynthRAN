"""Regression tests for Experiment-2 paired statistical inference."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from Experiments.Ex2_Flagship_Causal_5G_Transport import analysis as ex2_analysis


OUTCOME = "conditional_scheduled_delay_p95_s"
ARMS = ["native", "gap_permutation_r1", "gap_permutation_r2", "periodic"]
LOADS = ["below", "near", "above"]
LOAD_RATES = {"below": 20.0, "near": 30.0, "above": 40.0}


class AnalysisContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "runs").mkdir(parents=True)
        (self.root / "frozen-design.json").write_text(
            json.dumps(
                {
                    "expected_replays": 24,
                    "deployment_hash": "accepted-deployment",
                    "load_levels_mbps": LOAD_RATES,
                    "timing_arms": ARMS,
                    "source_seeds": [1, 2],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.background_config = {
            "achieved_rate_fraction_min": 0.95,
            "achieved_rate_fraction_max": 1.05,
            "sender_errors_allowed": 0,
        }
        self.manifest = {
            "study": {
                "transport_calibration": self.background_config,
                "statistics": {
                    "principal_outcomes": [OUTCOME],
                    "principal_contrast_ids": [
                        "native_minus_periodic",
                        "native_minus_mean_gap_permutation",
                    ],
                    "load_interactions": {
                        "near_minus_below": {"comparison": "near", "reference": "below"},
                        "above_minus_below": {"comparison": "above", "reference": "below"},
                    },
                    "bootstrap_resamples": 200,
                    "bootstrap_seed": 62002,
                    "multiplicity_adjustment": "none",
                    "practical_importance_policy": "No claim without an independent margin.",
                },
            }
        }

    @staticmethod
    def _penalty(seed: int, load: str) -> float:
        table = {
            (1, "below"): 0.1,
            (2, "below"): 0.2,
            (1, "near"): 0.4,
            (2, "near"): 0.6,
            (1, "above"): 1.0,
            (2, "above"): 1.2,
        }
        return table[(seed, load)]

    @staticmethod
    def _background(load: str, *, achieved_fraction: float = 1.0, errors: int = 0) -> dict:
        rate = LOAD_RATES[load]
        return {
            "sender": {
                "requested_payload_mbps": rate,
                "actual_payload_mbps": rate * achieved_fraction,
                "send_errors": errors,
            },
            "delivery_ratio": 0.999,
        }

    def _write_record(
        self,
        seed: int,
        load: str,
        arm: str,
        *,
        clock_valid: bool = True,
        achieved_fraction: float = 1.0,
    ) -> None:
        periodic = 1.0
        penalty = self._penalty(seed, load)
        values = {
            "periodic": periodic,
            "gap_permutation_r1": periodic + 0.05,
            "gap_permutation_r2": periodic - 0.05,
            "native": periodic + penalty,
        }
        directory = self.root / "runs" / f"seed{seed}-{load}-{arm}"
        directory.mkdir()
        (directory / "run-record.json").write_text(
            json.dumps(
                {
                    "seed": seed,
                    "load_level": load,
                    "timing_arm": arm,
                    "background_rate_mbps": LOAD_RATES[load],
                    "background": self._background(
                        load, achieved_fraction=achieved_fraction
                    ),
                    "measurement": {
                        "clock_contract_satisfied": clock_valid,
                        OUTCOME: values[arm],
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def _populate(self, *, invalid_background: tuple[int, str, str] | None = None) -> None:
        for seed in (1, 2):
            for load in LOADS:
                for arm in ARMS:
                    clock_valid = not (
                        seed == 2 and load == "near" and arm == "gap_permutation_r2"
                    )
                    fraction = 0.80 if invalid_background == (seed, load, arm) else 1.0
                    self._write_record(
                        seed,
                        load,
                        arm,
                        clock_valid=clock_valid,
                        achieved_fraction=fraction,
                    )

    def test_invalid_gap_arm_does_not_discard_native_periodic(self) -> None:
        self._populate()
        result = ex2_analysis.analysis(self.root, manifest=self.manifest)

        near = result["principal_contrasts"]["near"][OUTCOME]
        native_periodic = near["native_minus_periodic"]
        native_gap = near["native_minus_mean_gap_permutation"]

        self.assertEqual(native_periodic["n"], 2)
        self.assertEqual(native_periodic["included_source_seeds"], [1, 2])
        self.assertEqual(native_gap["n"], 1)
        self.assertEqual(native_gap["included_source_seeds"], [1])
        self.assertEqual(native_gap["excluded"][0]["seed"], 2)
        self.assertIn("gap_permutation_r2", native_gap["excluded"][0]["arms"])

    def test_load_interaction_pairs_the_same_source_seeds(self) -> None:
        self._populate()
        result = ex2_analysis.analysis(self.root, manifest=self.manifest)

        interaction = result["load_interactions"]["near_minus_below"][OUTCOME]
        native_periodic = interaction["native_minus_periodic"]
        native_gap = interaction["native_minus_mean_gap_permutation"]

        self.assertEqual(native_periodic["included_source_seeds"], [1, 2])
        self.assertAlmostEqual(native_periodic["mean"], 0.35, places=12)
        self.assertEqual(native_gap["included_source_seeds"], [1])
        self.assertAlmostEqual(native_gap["mean"], 0.30, places=12)
        self.assertEqual(native_gap["excluded"][0]["seed"], 2)
        self.assertIn("near", native_gap["excluded"][0]["load_reasons"])

    def test_invalid_background_arm_is_contrast_specific(self) -> None:
        self._populate(invalid_background=(1, "below", "gap_permutation_r1"))
        result = ex2_analysis.analysis(self.root, manifest=self.manifest)
        below = result["principal_contrasts"]["below"][OUTCOME]

        self.assertEqual(below["native_minus_periodic"]["included_source_seeds"], [1, 2])
        self.assertEqual(below["native_minus_mean_gap_permutation"]["included_source_seeds"], [2])
        exclusion = below["native_minus_mean_gap_permutation"]["excluded"][0]
        self.assertEqual(exclusion["seed"], 1)
        self.assertIn("background treatment invalid", exclusion["arms"]["gap_permutation_r1"])

    def test_missing_arm_reason_is_contrast_specific(self) -> None:
        def row(value: float) -> dict:
            return {
                "background_rate_mbps": 20.0,
                "background": self._background("below"),
                "measurement": {"clock_contract_satisfied": True, OUTCOME: value},
            }

        by_key = {
            (1, "below", "native"): row(1.2),
            (1, "below", "periodic"): row(1.0),
            (1, "below", "gap_permutation_r1"): row(1.1),
        }
        periodic, periodic_exclusion = ex2_analysis._seed_contrast(
            by_key,
            seed=1,
            load="below",
            outcome=OUTCOME,
            contrast="native_minus_periodic",
            background_config=self.background_config,
        )
        gaps, gap_exclusion = ex2_analysis._seed_contrast(
            by_key,
            seed=1,
            load="below",
            outcome=OUTCOME,
            contrast="native_minus_mean_gap_permutation",
            background_config=self.background_config,
        )

        self.assertAlmostEqual(periodic, 0.2)
        self.assertIsNone(periodic_exclusion)
        self.assertIsNone(gaps)
        self.assertEqual(gap_exclusion["reason"], "missing treatment cell")
        self.assertEqual(gap_exclusion["arms"], ["gap_permutation_r2"])

    def test_output_declares_pointwise_not_familywise_inference(self) -> None:
        self._populate()
        result = ex2_analysis.analysis(self.root, manifest=self.manifest)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["inference_policy"]["multiplicity_adjustment"], "none")
        self.assertIn("pointwise", result["inference_policy"]["confidence_intervals"])
        self.assertIn("independent margin", result["inference_policy"]["practical_importance"])
        self.assertEqual(
            result["inference_policy"]["load_treatment_validity"]["achieved_rate_fraction_min"],
            0.95,
        )


if __name__ == "__main__":
    unittest.main()
