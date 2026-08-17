from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from synthran.research import (
    CampaignCondition,
    LoadSpec,
    MeasurementSpec,
    ResearchError,
    ResearchExperimentSpec,
    analyze_campaign,
    bootstrap_paired_difference,
    build_campaign,
    build_run_summary,
    load_metrics,
    network_metrics,
    probe_metrics,
    save_campaign,
    save_research_spec,
    telemetry_metrics,
)


class ResearchExperimentSpecTests(unittest.TestCase):
    def test_baseline_contract_and_nominal_event_count(self) -> None:
        spec = ResearchExperimentSpec(
            campaign_id="campaign-c01",
            run_id="campaign-c01-b01-baseline",
            network_run_id="network-accepted",
            condition="baseline",
            measurement=MeasurementSpec(duration_seconds=180),
        )
        self.assertEqual(spec.expected_events_per_sensor, 18)
        self.assertEqual(spec.expected_events_total, 180)
        self.assertFalse(spec.load.enabled)

    def test_fractional_load_resolves_against_capacity(self) -> None:
        load = LoadSpec(
            enabled=True,
            target_fraction=0.8,
            reference_capacity_bps=10_000_000,
            parallel_flows=2,
        )
        self.assertEqual(load.resolved_target_bps, 8_000_000)

    def test_loaded_condition_requires_enabled_load(self) -> None:
        with self.assertRaisesRegex(ResearchError, "enabled load"):
            ResearchExperimentSpec(
                campaign_id="campaign-c01",
                run_id="campaign-c01-b01-high",
                network_run_id="network-accepted",
                condition="high",
            )

    def test_baseline_rejects_load(self) -> None:
        with self.assertRaisesRegex(ResearchError, "baseline"):
            ResearchExperimentSpec(
                campaign_id="campaign-c01",
                run_id="campaign-c01-b01-baseline",
                network_run_id="network-accepted",
                condition="baseline",
                load=LoadSpec(enabled=True, target_bps=1_000_000),
            )

    def test_tcp_background_load_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResearchError, "protocol"):
            LoadSpec(enabled=True, protocol="tcp", target_bps=1_000_000)

    def test_spec_serialization_preserves_resolved_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "spec.json"
            spec = ResearchExperimentSpec(
                campaign_id="campaign-c01",
                run_id="campaign-c01-b01-high",
                network_run_id="network-accepted",
                condition="high",
                cooja_seed=17,
                sensor_period_seconds=5,
                measurement=MeasurementSpec(
                    warmup_seconds=10,
                    duration_seconds=120,
                    sample_interval_seconds=2.0,
                    probe_interval_seconds=0.5,
                ),
                load=LoadSpec(
                    enabled=True,
                    target_fraction=0.8,
                    reference_capacity_bps=20_000_000,
                    parallel_flows=2,
                ),
                probe_target="192.0.2.25",
            )
            save_research_spec(spec, path)
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                value["schema"], "synthran/research-experiment/v1alpha1"
            )
            self.assertEqual(value["load"]["resolved_target_bps"], 16_000_000)


class CampaignTests(unittest.TestCase):
    def _conditions(self) -> tuple[CampaignCondition, ...]:
        return (
            CampaignCondition("baseline"),
            CampaignCondition("load-50", load_fraction=0.5),
            CampaignCondition("load-80", load_fraction=0.8),
        )

    def test_schedule_is_deterministic_and_blocked(self) -> None:
        first = build_campaign(
            campaign_id="campaign-c01",
            network_run_id="network-accepted",
            seeds=(7, 17, 27),
            conditions=self._conditions(),
            campaign_seed=123,
        )
        second = build_campaign(
            campaign_id="campaign-c01",
            network_run_id="network-accepted",
            seeds=(7, 17, 27),
            conditions=self._conditions(),
            campaign_seed=123,
        )
        self.assertEqual(first.runs, second.runs)
        self.assertEqual(len(first.runs), 9)
        for block in range(1, 4):
            names = {
                run.condition for run in first.runs if run.block == block
            }
            self.assertEqual(names, {"baseline", "load-50", "load-80"})

    def test_campaign_serialization_normalizes_targets_in_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign = build_campaign(
                campaign_id="campaign-c01",
                network_run_id="network-accepted",
                seeds=(7,),
                conditions=(
                    CampaignCondition("baseline"),
                    CampaignCondition("high", target_bps=5_000_000),
                ),
                campaign_seed=42,
            )
            path = Path(temporary) / "campaign.json"
            save_campaign(campaign, path)
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                value["schema"], "synthran/research-campaign/v1alpha1"
            )
            self.assertEqual(
                set(value["runs"][0]),
                {"ordinal", "block", "seed", "condition", "run_id"},
            )

    def test_invalid_condition_and_campaign_identifiers_fail_before_schedule(self) -> None:
        with self.assertRaisesRegex(ResearchError, "condition"):
            CampaignCondition("Load 80", load_fraction=0.8)
        with self.assertRaisesRegex(ResearchError, "campaign ID"):
            build_campaign(
                campaign_id="bad campaign",
                network_run_id="network-accepted",
                seeds=(1,),
                conditions=self._conditions(),
                campaign_seed=1,
            )

    def test_duplicate_seed_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResearchError, "unique"):
            build_campaign(
                campaign_id="campaign-c01",
                network_run_id="network-accepted",
                seeds=(7, 7),
                conditions=self._conditions(),
                campaign_seed=1,
            )


class ResearchMetricTests(unittest.TestCase):
    def _telemetry(
        self, sensor: str, sequence: int, second: int
    ) -> dict[str, object]:
        at = datetime(2026, 8, 17, tzinfo=timezone.utc) + timedelta(
            seconds=second
        )
        return {
            "schema": "synthran/telemetry/v1alpha1",
            "run_id": "run",
            "sensor_id": sensor,
            "sequence": sequence,
            "sensor_time_ms": second * 1000,
            "value_milli": sequence,
            "received_at_utc": at.isoformat().replace("+00:00", "Z"),
        }

    def test_telemetry_delivery_interarrival_and_sequence_gap_metrics(self) -> None:
        complete = []
        gapped = []
        for sensor in range(1, 11):
            sensor_id = f"sensor-{sensor:02d}"
            complete.extend(
                [
                    self._telemetry(sensor_id, 1, 0),
                    self._telemetry(sensor_id, 2, 5),
                    self._telemetry(sensor_id, 3, 10),
                ]
            )
            gapped.extend(
                [
                    self._telemetry(sensor_id, 1, 0),
                    self._telemetry(sensor_id, 3, 10),
                ]
            )
        metrics = telemetry_metrics(
            complete, sensor_count=10, expected_per_sensor=3
        )
        self.assertEqual(metrics["delivery_ratio"], 1.0)
        self.assertEqual(metrics["inter_arrival_ms"]["median"], 5000.0)
        degraded = telemetry_metrics(
            gapped, sensor_count=10, expected_per_sensor=3
        )
        self.assertEqual(degraded["sequence_gaps"], 10)
        self.assertAlmostEqual(degraded["delivery_ratio"], 20 / 30)

    def test_probe_network_and_load_metrics(self) -> None:
        probe = probe_metrics(
            [
                {"rtt_ms": 10.0, "timeout": False},
                {"rtt_ms": 12.0, "timeout": False},
                {"rtt_ms": None, "timeout": True},
                {"rtt_ms": 14.0, "timeout": False},
            ]
        )
        self.assertEqual(probe["timeouts"], 1)
        self.assertEqual(probe["rtt_ms"]["median"], 12.0)
        network = network_metrics(
            [
                {
                    "elapsed_seconds": 0.0,
                    "ue_tx_bytes": 100,
                    "ue_rx_bytes": 200,
                },
                {
                    "elapsed_seconds": 10.0,
                    "ue_tx_bytes": 1100,
                    "ue_rx_bytes": 2200,
                },
            ]
        )
        self.assertEqual(network["ue_tx_bps"], 800.0)
        load = load_metrics(
            [{"bits_per_second": 8_100_000}], target_bps=8_000_000
        )
        self.assertAlmostEqual(load["target_ratio"], 1.0125)


class SummaryAndAnalysisTests(unittest.TestCase):
    def _summary(
        self, seed: int, condition: str, rtt: float
    ) -> dict[str, object]:
        return {
            "schema": "synthran/research-summary/v1alpha1",
            "campaign_id": "campaign-c01",
            "run_id": f"run-{seed}-{condition}",
            "network_run_id": "network-accepted",
            "condition": condition,
            "cooja_seed": seed,
            "telemetry": {
                "delivery_ratio": 1.0,
                "inter_arrival_ms": {"p95": 5000.0},
            },
            "probe": {
                "rtt_ms": {"median": rtt, "p95": rtt + 1.0},
                "rtt_jitter_ms": {"median": 1.0},
            },
            "network": {"ue_tx_bps": 1000.0},
            "load_result": {
                "measured_bps": {
                    "mean": 0.0
                    if condition == "baseline"
                    else 8_000_000.0
                }
            },
            "ready_for_campaign_analysis": True,
        }

    def test_campaign_analysis_pairs_matching_seed_blocks(self) -> None:
        campaign = build_campaign(
            campaign_id="campaign-c01",
            network_run_id="network-accepted",
            seeds=(7, 17),
            conditions=(
                CampaignCondition("baseline"),
                CampaignCondition("high", load_fraction=0.8),
            ),
            campaign_seed=9,
        )
        analysis = analyze_campaign(
            campaign,
            [
                self._summary(7, "baseline", 10.0),
                self._summary(7, "high", 20.0),
                self._summary(17, "baseline", 12.0),
                self._summary(17, "high", 24.0),
            ],
        )
        paired = analysis["paired_vs_baseline"]["high"]["rtt_median_ms"]
        self.assertEqual(paired["n_pairs"], 2)
        self.assertEqual(paired["median_difference"], 11.0)

    def test_bootstrap_is_deterministic(self) -> None:
        first = bootstrap_paired_difference(
            [1, 2, 3], [2, 4, 6], seed=7, samples=500
        )
        second = bootstrap_paired_difference(
            [1, 2, 3], [2, 4, 6], seed=7, samples=500
        )
        self.assertEqual(first, second)

    def test_run_summary_rejects_unachieved_load_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = ResearchExperimentSpec(
                campaign_id="campaign-c01",
                run_id="campaign-c01-b01-high",
                network_run_id="network-accepted",
                condition="high",
                sensor_period_seconds=10,
                measurement=MeasurementSpec(duration_seconds=30),
                load=LoadSpec(enabled=True, target_bps=10_000_000),
                probe_target="192.0.2.1",
            )
            summary = build_run_summary(
                spec=spec,
                run_directory=root,
                telemetry_records=[
                    self._telemetry_record(sensor, sequence)
                    for sensor in range(1, 11)
                    for sequence in range(1, 4)
                ],
                probe_records=[{"rtt_ms": 10.0, "timeout": False}],
                network_records=[
                    {
                        "elapsed_seconds": 0.0,
                        "ue_tx_bytes": 0,
                        "ue_rx_bytes": 0,
                    },
                    {
                        "elapsed_seconds": 10.0,
                        "ue_tx_bytes": 1000,
                        "ue_rx_bytes": 1000,
                    },
                ],
                load_records=[{"bits_per_second": 5_000_000}],
            )
            self.assertFalse(summary["validity"]["load_target_achieved"])
            self.assertFalse(summary["ready_for_campaign_analysis"])

    def _telemetry_record(
        self, sensor: int, sequence: int
    ) -> dict[str, object]:
        return {
            "schema": "synthran/telemetry/v1alpha1",
            "run_id": "campaign-c01-b01-high",
            "sensor_id": f"sensor-{sensor:02d}",
            "sequence": sequence,
            "sensor_time_ms": sequence * 1000,
            "value_milli": sequence,
            "received_at_utc": datetime(
                2026, 8, 17, 6, 0, sequence, tzinfo=timezone.utc
            )
            .isoformat()
            .replace("+00:00", "Z"),
        }


if __name__ == "__main__":
    unittest.main()
