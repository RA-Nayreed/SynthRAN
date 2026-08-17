from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.experiment import ExperimentError
from synthran.research import (
    LoadProfile,
    ResearchSpec,
    analyze_campaign,
    analyze_research_run,
    build_campaign_plan,
    percentile,
    probe_metrics,
    summarize_campaign,
    telemetry_metrics,
)


class ResearchContractTests(unittest.TestCase):
    def test_baseline_spec_derives_collection_and_measurement_targets(self) -> None:
        spec = ResearchSpec(
            campaign_id="research-c01",
            run_id="research-c01-s1-baseline",
            network_run_id="network-acceptance",
            condition="baseline",
            cooja_seed=1,
            warmup_seconds=15,
            measurement_seconds=180,
            sensor_period_seconds=10,
            load=LoadProfile("baseline"),
        )
        self.assertEqual(spec.minimum_per_sensor, 22)
        self.assertEqual(spec.expected_events, 180)
        self.assertEqual(spec.collection_timeout_seconds, 315)
        self.assertEqual(spec.load.target_kbps, 0.0)

    def test_congestion_requires_calibrated_reference(self) -> None:
        with self.assertRaises(ExperimentError):
            LoadProfile("congestion", target_fraction=0.8)

    def test_congestion_target_is_relative_to_reference(self) -> None:
        load = LoadProfile("congestion", target_fraction=0.8, reference_kbps=12500)
        self.assertEqual(load.target_kbps, 10000)

    def test_window_must_fit_accepted_collector_limits(self) -> None:
        with self.assertRaises(ExperimentError):
            ResearchSpec(
                campaign_id="research-c01",
                run_id="research-c01-too-long",
                network_run_id="network-acceptance",
                condition="baseline",
                cooja_seed=1,
                warmup_seconds=600,
                measurement_seconds=3000,
                sensor_period_seconds=60,
                load=LoadProfile("baseline"),
            )

    def test_event_requirement_cannot_exceed_acceptance_limit(self) -> None:
        with self.assertRaises(ExperimentError):
            ResearchSpec(
                campaign_id="research-c01",
                run_id="research-c01-too-fast",
                network_run_id="network-acceptance",
                condition="baseline",
                cooja_seed=1,
                warmup_seconds=15,
                measurement_seconds=180,
                sensor_period_seconds=1,
                load=LoadProfile("baseline"),
            )

    def test_campaign_is_deterministic_and_block_randomized(self) -> None:
        first = build_campaign_plan(
            campaign_id="research-c01",
            network_run_id="network-acceptance",
            seeds=[11, 22],
            congestion_fractions=[0.5, 0.8, 0.95],
            reference_kbps=10000,
            randomization_seed=7,
        )
        second = build_campaign_plan(
            campaign_id="research-c01",
            network_run_id="network-acceptance",
            seeds=[11, 22],
            congestion_fractions=[0.5, 0.8, 0.95],
            reference_kbps=10000,
            randomization_seed=7,
        )
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.runs), 8)
        for seed in (11, 22):
            block = [run for run in first.runs if run.seed == seed]
            self.assertEqual(
                {run.target_fraction for run in block},
                {0.0, 0.5, 0.8, 0.95},
            )

    def test_percentile_interpolates(self) -> None:
        self.assertEqual(percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertAlmostEqual(percentile([1, 2, 3, 4], 0.95), 3.85)


class ResearchMetricTests(unittest.TestCase):
    def _telemetry(self, *, minute: int = 0) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for sensor in range(1, 11):
            for sequence in range(1, 4):
                records.append(
                    {
                        "sensor_id": f"sensor-{sensor:02d}",
                        "sequence": sequence,
                        "received_at_utc": (
                            f"2026-08-17T06:{minute:02d}:{sensor + sequence:02d}Z"
                        ),
                    }
                )
        return records

    def test_telemetry_metrics_use_collector_clock_only(self) -> None:
        result = telemetry_metrics(self._telemetry(), expected_events=30)
        self.assertEqual(result["delivery_ratio"], 1.0)
        self.assertEqual(result["sequence_gap_count"], 0)
        self.assertIsNotNone(result["inter_arrival_median_ms"])

    def test_probe_metrics_report_tail_and_timeouts(self) -> None:
        result = probe_metrics(
            [
                {"success": True, "rtt_ms": 10.0},
                {"success": True, "rtt_ms": 20.0},
                {"success": False, "rtt_ms": None},
            ]
        )
        self.assertEqual(result["probe_attempts"], 3)
        self.assertEqual(result["probe_successes"], 2)
        self.assertAlmostEqual(result["probe_timeout_rate"], 1 / 3)
        self.assertGreater(result["rtt_p95_ms"], 19.0)

    def test_run_analysis_excludes_telemetry_outside_measurement_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "research-c01-s1-baseline"
            run.mkdir()
            spec = ResearchSpec(
                campaign_id="research-c01",
                run_id=run.name,
                network_run_id="network-acceptance",
                condition="baseline",
                cooja_seed=1,
                warmup_seconds=0,
                measurement_seconds=30,
                sensor_period_seconds=10,
                load=LoadProfile("baseline"),
            )
            (run / "research-spec.json").write_text(
                json.dumps(spec.to_dict()), encoding="utf-8"
            )
            (run / "research-window.json").write_text(
                json.dumps(
                    {
                        "schema": "synthran/research-window/v1alpha1",
                        "start_utc": "2026-08-17T06:00:00Z",
                        "end_utc": "2026-08-17T06:01:00Z",
                        "start_monotonic_seconds": 1.0,
                        "end_monotonic_seconds": 61.0,
                    }
                ),
                encoding="utf-8",
            )
            records = self._telemetry(minute=0) + self._telemetry(minute=2)
            with (run / "telemetry.jsonl").open("w", encoding="utf-8") as stream:
                for record in records:
                    stream.write(json.dumps(record) + "\n")
            (run / "research-probe.jsonl").write_text(
                json.dumps({"success": True, "rtt_ms": 12.0}) + "\n",
                encoding="utf-8",
            )
            (run / "research-network.jsonl").write_text(
                json.dumps(
                    {
                        "monotonic_seconds": 1.0,
                        "ue_tx_bytes": 100,
                        "ue_rx_bytes": 50,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "monotonic_seconds": 31.0,
                        "ue_tx_bytes": 1100,
                        "ue_rx_bytes": 550,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = analyze_research_run(run)
            self.assertEqual(result["telemetry"]["received_events"], 30)
            self.assertEqual(result["telemetry"]["delivery_ratio"], 1.0)
            self.assertTrue((run / "research-summary.json").is_file())

    def test_campaign_analysis_rejects_invalid_run_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "research-c01-s1-baseline"
            run.mkdir()
            (run / "research-evidence.json").write_text(
                json.dumps(
                    {
                        "schema": "synthran/research-evidence/v1alpha1",
                        "valid": False,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ExperimentError):
                analyze_campaign(
                    campaign_id="research-c01",
                    run_root=root,
                    run_ids=[run.name],
                    destination=root / "campaign-summary.json",
                )

    def test_campaign_summary_reports_paired_seed_effect(self) -> None:
        baseline = {
            "campaign_id": "research-c01",
            "cooja_seed": 11,
            "condition": "baseline",
            "target_fraction": 0.0,
            "telemetry": {"delivery_ratio": 1.0},
            "probe": {"rtt_p95_ms": 10.0},
        }
        congestion = {
            "campaign_id": "research-c01",
            "cooja_seed": 11,
            "condition": "congestion",
            "target_fraction": 0.8,
            "telemetry": {"delivery_ratio": 0.9},
            "probe": {"rtt_p95_ms": 25.0},
        }
        result = summarize_campaign(
            campaign_id="research-c01", run_results=[baseline, congestion]
        )
        effect = result["paired_effects"]["congestion:0.8000"]
        self.assertEqual(effect["paired_runs"], 1)
        self.assertAlmostEqual(effect["delivery_ratio_delta_median"], -0.1)
        self.assertEqual(effect["rtt_p95_delta_median_ms"], 15.0)

    def test_campaign_summary_rejects_cross_campaign_run(self) -> None:
        with self.assertRaises(ExperimentError):
            summarize_campaign(
                campaign_id="research-c01",
                run_results=[
                    {
                        "campaign_id": "other",
                        "condition": "baseline",
                        "target_fraction": 0.0,
                        "telemetry": {"delivery_ratio": 1.0},
                        "probe": {"rtt_p95_ms": 10.0},
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
