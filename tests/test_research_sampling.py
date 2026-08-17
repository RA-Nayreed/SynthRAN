from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from synthran.research import (
    NETWORK_SAMPLE_SCHEMA,
    ResearchError,
    load_jsonl,
    network_metrics,
)
from synthran.research_sampling import ResearchNetworkSampler, _active_run_owned_upf


def _ready_status() -> dict[str, object]:
    return {"conditions": [{"type": "Ready", "status": "True"}]}


class UpfOwnershipTests(unittest.TestCase):
    def test_discovers_exact_active_run_owned_upf(self) -> None:
        payload = {
            "items": [
                {
                    "metadata": {
                        "name": "open5gs-upf-abc",
                        "labels": {"synthran.run/id": "network-accepted"},
                    },
                    "status": _ready_status(),
                }
            ]
        }
        with patch(
            "synthran.research_sampling.base_runtime._remote",
            return_value=json.dumps(payload),
        ):
            name = _active_run_owned_upf(MagicMock(), "network-accepted")
        self.assertEqual(name, "open5gs-upf-abc")

    def test_foreign_upf_is_rejected(self) -> None:
        payload = {
            "items": [
                {
                    "metadata": {
                        "name": "open5gs-upf-abc",
                        "labels": {"synthran.run/id": "another-run"},
                    },
                    "status": _ready_status(),
                }
            ]
        }
        with patch(
            "synthran.research_sampling.base_runtime._remote",
            return_value=json.dumps(payload),
        ):
            with self.assertRaisesRegex(ResearchError, "exactly one"):
                _active_run_owned_upf(MagicMock(), "network-accepted")

    def test_non_ready_owned_upf_is_rejected(self) -> None:
        payload = {
            "items": [
                {
                    "metadata": {
                        "name": "open5gs-upf-abc",
                        "labels": {"synthran.run/id": "network-accepted"},
                    },
                    "status": {"conditions": []},
                }
            ]
        }
        with patch(
            "synthran.research_sampling.base_runtime._remote",
            return_value=json.dumps(payload),
        ):
            with self.assertRaisesRegex(ResearchError, "Ready"):
                _active_run_owned_upf(MagicMock(), "network-accepted")


class SynchronizedSamplerTests(unittest.TestCase):
    def test_sample_combines_ue_upf_and_ingress_evidence(self) -> None:
        ue = {
            "rx_bytes": 100,
            "tx_bytes": 200,
            "rx_packets": 10,
            "tx_packets": 20,
            "rx_dropped": 1,
            "tx_dropped": 2,
        }
        upf = {
            "rx_bytes": 300,
            "tx_bytes": 400,
            "rx_packets": 30,
            "tx_packets": 40,
            "rx_dropped": 3,
            "tx_dropped": 4,
        }

        def counters(_inventory, *, pod, interface, container=None):
            if pod == "ue-pod":
                self.assertEqual(interface, "tun_srsue1")
                self.assertEqual(container, "ue")
                return ue
            self.assertEqual(pod, "upf-pod")
            self.assertEqual(interface, "ogstun")
            self.assertIsNone(container)
            return upf

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "network-samples.jsonl"
            with (
                patch(
                    "synthran.research_sampling._active_run_owned_upf",
                    return_value="upf-pod",
                ),
                patch(
                    "synthran.research_sampling._interface_counters",
                    side_effect=counters,
                ),
                patch("synthran.research_sampling._ingress_snapshot") as ingress,
            ):
                ingress.return_value.accepted_connections = 10
                ingress.return_value.upstream_bytes = 500
                ingress.return_value.downstream_bytes = 600
                sampler = ResearchNetworkSampler(
                    inventory=MagicMock(),
                    network_run_id="network-accepted",
                    experiment_run_id="research-run",
                    ue_pod="ue-pod",
                    interval_seconds=1.0,
                    destination=destination,
                )
                sampler._started = 1.0
                with patch(
                    "synthran.research_sampling.time.monotonic",
                    return_value=2.5,
                ):
                    sampler._sample()
            records = load_jsonl(destination, schema=NETWORK_SAMPLE_SCHEMA)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["ue_tx_bytes"], 200)
        self.assertEqual(record["upf_rx_bytes"], 300)
        self.assertEqual(record["ingress_upstream_bytes"], 500)
        self.assertEqual(record["ue_interface"], "tun_srsue1")
        self.assertEqual(record["upf_interface"], "ogstun")


class TransportMetricTests(unittest.TestCase):
    def test_full_transport_samples_derive_all_path_deltas(self) -> None:
        first = {
            "elapsed_seconds": 0.0,
            "ue_tx_bytes": 100,
            "ue_rx_bytes": 200,
            "ue_tx_packets": 10,
            "ue_rx_packets": 20,
            "ue_tx_dropped": 1,
            "ue_rx_dropped": 2,
            "upf_tx_bytes": 300,
            "upf_rx_bytes": 400,
            "upf_tx_packets": 30,
            "upf_rx_packets": 40,
            "upf_tx_dropped": 3,
            "upf_rx_dropped": 4,
            "ingress_accepted_connections": 5,
            "ingress_upstream_bytes": 500,
            "ingress_downstream_bytes": 600,
        }
        second = {
            **first,
            "elapsed_seconds": 10.0,
            "ue_tx_bytes": 1100,
            "ue_rx_bytes": 2200,
            "upf_tx_bytes": 3300,
            "upf_rx_bytes": 4400,
            "ingress_accepted_connections": 15,
            "ingress_upstream_bytes": 1500,
            "ingress_downstream_bytes": 2600,
        }
        metrics = network_metrics([first, second])
        self.assertTrue(metrics["transport_path_complete"])
        self.assertEqual(metrics["ue_tx_bps"], 800.0)
        self.assertEqual(metrics["upf_rx_bps"], 3200.0)
        self.assertEqual(metrics["ingress_accepted_connections_delta"], 10)
        self.assertEqual(metrics["ingress_downstream_bytes_delta"], 2000)

    def test_ue_only_samples_are_not_full_transport_evidence(self) -> None:
        metrics = network_metrics(
            [
                {"elapsed_seconds": 0.0, "ue_tx_bytes": 0, "ue_rx_bytes": 0},
                {"elapsed_seconds": 1.0, "ue_tx_bytes": 10, "ue_rx_bytes": 10},
            ]
        )
        self.assertFalse(metrics["transport_path_complete"])


if __name__ == "__main__":
    unittest.main()
