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
                    "load_levels_mbps": {"below": 20, "near": 30, "above": 40},
                    "timing_arms": ARMS,
                    "source_seeds": [1, 2],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.manifest = {
            "study": {
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
                }
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

    def _write_record(
        self,
        seed: int,
        load: str,
        arm: str,
        *,
        clock_valid: bool = True,
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
                    "measurement": {
                        "clock_contract_satisfied": clock_valid,
                        OUTCOME: values[arm],
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def _populate(self) -> None:
        for seed in (1, 2):
            for load in LOADS:
                for arm in ARMS:
                    clock_valid = not (
                        seed == 2 and load == "near" and arm == "gap_permutation_r2"
                    )
                    self._write_record(seed, load, arm, clock_valid=clock_valid)

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

    def test_missing_arm_reason_is_contrast_specific(self) -> None:
        by_key = {
            (1, "below", "native"): {
                "measurement": {"clock_contract_satisfied": True, OUTCOME: 1.2}
            },
            (1, "below", "periodic"): {
                "measurement": {"clock_contract_satisfied": True, OUTCOME: 1.0}
            },
            (1, "below", "gap_permutation_r1"): {
                "measurement": {"clock_contract_satisfied": True, OUTCOME: 1.1}
            },
        }
        periodic, periodic_exclusion = ex2_analysis._seed_contrast(
            by_key,
            seed=1,
            load="below",
            outcome=OUTCOME,
            contrast="native_minus_periodic",
        )
        gaps, gap_exclusion = ex2_analysis._seed_contrast(
            by_key,
            seed=1,
            load="below",
            outcome=OUTCOME,
            contrast="native_minus_mean_gap_permutation",
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


if __name__ == "__main__":
    unittest.main()
