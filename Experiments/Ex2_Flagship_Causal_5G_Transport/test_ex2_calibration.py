"""Regression tests for the Experiment-2 revision-2 load calibration contract."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Experiments.Ex2_Flagship_Causal_5G_Transport import campaign


class CalibrationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = {"deployment_hash": "accepted-deployment"}

    @staticmethod
    def manifest(rates: list[float]) -> dict:
        return {
            "study": {
                "transport_calibration": {
                    "packet_bytes": 1200,
                    "probe_duration_seconds": 10,
                    "repeats_per_rate": 3,
                    "offered_payload_mbps_grid": rates,
                    "delivery_threshold": 0.98,
                    "achieved_rate_fraction_min": 0.95,
                    "achieved_rate_fraction_max": 1.05,
                    "sender_errors_allowed": 0,
                    "selection_rule": "revision-2 test rule",
                    "base_port": 39001,
                }
            }
        }

    @staticmethod
    def probe(rate: float, *, delivery: float, achieved_fraction: float = 1.0, send_errors: int = 0) -> dict:
        attempted = 1000
        received = round(attempted * delivery)
        return {
            "sender": {
                "requested_payload_mbps": rate,
                "actual_payload_mbps": rate * achieved_fraction,
                "send_errors": send_errors,
                "packets_attempted": attempted,
            },
            "receiver": {"packets_received": received},
            "packets_attempted": attempted,
            "packets_received": received,
            "packets_lost": attempted - received,
            "delivery_ratio": delivery,
        }

    def run_calibration(self, fake_probe, rates: list[float]):
        with (
            patch.object(
                campaign,
                "_transport_context",
                return_value=({"device": "qhat03"}, "172.28.2.77", "proved-route"),
            ),
            patch.object(campaign, "_udp_probe", side_effect=fake_probe) as probe_mock,
        ):
            result = campaign.calibration(
                self.root,
                manifest=self.manifest(rates),
                environment=self.environment,
            )
        return result, probe_mock

    def test_first_valid_crossing_selects_three_levels_and_stops_sweep(self) -> None:
        deliveries = {10.0: 0.999, 20.0: 0.995, 30.0: 0.970, 40.0: 0.500}

        def fake_probe(_environment, _competitor, _broker, *, rate, **_kwargs):
            return self.probe(rate, delivery=deliveries[float(rate)])

        result, probe_mock = self.run_calibration(fake_probe, [10, 20, 30, 40])

        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected_mbps"], {"below": 10.0, "near": 20.0, "above": 30.0})
        self.assertEqual(probe_mock.call_count, 9)
        self.assertEqual(len(result["rate_summaries"]), 3)
        self.assertTrue(all(row["generator_valid"] for row in result["probes"]))
        self.assertEqual(result["schema_version"], 2)

    def test_invalid_generator_is_retained_and_blocks_confirmation(self) -> None:
        def fake_probe(_environment, _competitor, _broker, *, rate, **_kwargs):
            fraction = 0.80 if float(rate) == 20.0 else 1.0
            return self.probe(rate, delivery=0.999, achieved_fraction=fraction)

        with (
            patch.object(
                campaign,
                "_transport_context",
                return_value=({"device": "qhat03"}, "172.28.2.77", "proved-route"),
            ),
            patch.object(campaign, "_udp_probe", side_effect=fake_probe) as probe_mock,
            self.assertRaisesRegex(RuntimeError, "sender-rate contract"),
        ):
            campaign.calibration(
                self.root,
                manifest=self.manifest([10, 20, 30]),
                environment=self.environment,
            )

        retained = json.loads((self.root / "calibration/load-selection.json").read_text())
        self.assertEqual(retained["status"], "invalid_generator")
        self.assertEqual(probe_mock.call_count, 6)
        invalid = [row for row in retained["probes"] if not row["generator_valid"]]
        self.assertEqual(len(invalid), 3)
        self.assertTrue(
            all(
                "achieved payload rate outside prespecified validity interval"
                in row["generator_invalid_reasons"]
                for row in invalid
            )
        )

    def test_unbracketed_sweep_retains_every_completed_probe(self) -> None:
        def fake_probe(_environment, _competitor, _broker, *, rate, **_kwargs):
            return self.probe(rate, delivery=0.999)

        with (
            patch.object(
                campaign,
                "_transport_context",
                return_value=({"device": "qhat03"}, "172.28.2.77", "proved-route"),
            ),
            patch.object(campaign, "_udp_probe", side_effect=fake_probe) as probe_mock,
            self.assertRaisesRegex(RuntimeError, "unbracketed"),
        ):
            campaign.calibration(
                self.root,
                manifest=self.manifest([10, 20, 30]),
                environment=self.environment,
            )

        retained = json.loads((self.root / "calibration/load-selection.json").read_text())
        self.assertEqual(retained["status"], "unbracketed")
        self.assertIsNone(retained["selected_mbps"])
        self.assertEqual(len(retained["probes"]), 9)
        self.assertEqual(probe_mock.call_count, 9)

    def test_retained_failed_calibration_is_not_silently_reexecuted(self) -> None:
        destination = self.root / "calibration/load-selection.json"
        destination.parent.mkdir(parents=True)
        destination.write_text('{"status":"unbracketed"}\n', encoding="utf-8")

        with (
            patch.object(campaign, "_transport_context") as transport_mock,
            self.assertRaisesRegex(RuntimeError, "already retained"),
        ):
            campaign.calibration(
                self.root,
                manifest=self.manifest([10, 20, 30]),
                environment=self.environment,
            )
        transport_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
