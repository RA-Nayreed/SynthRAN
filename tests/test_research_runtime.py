from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.live_preflight import CommandResult
from synthran.research import (
    LoadSpec,
    MeasurementSpec,
    ResearchExperimentSpec,
    load_jsonl,
)
from synthran.research_runtime import (
    _base_cleanup_reproved,
    _extract_iperf_bps,
    _parse_load_log,
    _parse_probe_log,
    _prove_target_route,
    _runtime_overrides,
)


class IperfParsingTests(unittest.TestCase):
    def test_sum_received_is_preferred(self) -> None:
        value = {
            "end": {
                "sum_received": {"bits_per_second": 8_100_000.0},
                "sum_sent": {"bits_per_second": 8_000_000.0},
            }
        }
        self.assertEqual(_extract_iperf_bps(value), 8_100_000.0)

    def test_streams_are_summed_when_aggregate_is_absent(self) -> None:
        value = {
            "end": {
                "streams": [
                    {"receiver": {"bits_per_second": 2_000_000.0}},
                    {"receiver": {"bits_per_second": 3_000_000.0}},
                ]
            }
        }
        self.assertEqual(_extract_iperf_bps(value), 5_000_000.0)

    def test_load_log_becomes_structured_jsonl_with_aggregate_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "load.log"
            destination = root / "load.jsonl"
            log.write_text(
                "prefix\n"
                + json.dumps(
                    {
                        "end": {
                            "sum_received": {
                                "bits_per_second": 7_950_000
                            }
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            _parse_load_log(
                log,
                destination,
                target_bps=8_000_000,
                protocol="udp",
            )
            records = load_jsonl(
                destination,
                schema="synthran/research-load-result/v1alpha1",
            )
            self.assertEqual(records[0]["bits_per_second"], 7_950_000.0)
            self.assertEqual(records[0]["target_bps"], 8_000_000)


class ProbeParsingTests(unittest.TestCase):
    def test_probe_log_records_internal_sequence_timeouts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "ping.log"
            destination = root / "probe.jsonl"
            log.write_text(
                "[1000.000000] 64 bytes from 192.0.2.1: icmp_seq=1 ttl=64 time=11.2 ms\n"
                "[1002.000000] 64 bytes from 192.0.2.1: icmp_seq=3 ttl=64 time=13.4 ms\n",
                encoding="utf-8",
            )
            _parse_probe_log(log, destination, interval_seconds=1.0)
            records = load_jsonl(
                destination,
                schema="synthran/research-probe/v1alpha1",
            )
            self.assertEqual(len(records), 3)
            self.assertFalse(records[0]["timeout"])
            self.assertTrue(records[1]["timeout"])
            self.assertEqual(records[2]["rtt_ms"], 13.4)

    def test_probe_window_infers_leading_and_trailing_timeouts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "ping.log"
            destination = root / "probe.jsonl"
            log.write_text(
                "[1001.000000] 64 bytes from 192.0.2.1: icmp_seq=2 ttl=64 time=10.0 ms\n"
                "[1003.000000] 64 bytes from 192.0.2.1: icmp_seq=4 ttl=64 time=12.0 ms\n",
                encoding="utf-8",
            )
            _parse_probe_log(
                log,
                destination,
                interval_seconds=1.0,
                window_started_at_utc=datetime.fromtimestamp(
                    1000.0, timezone.utc
                ),
                window_ended_at_utc=datetime.fromtimestamp(
                    1004.0, timezone.utc
                ),
            )
            records = load_jsonl(
                destination,
                schema="synthran/research-probe/v1alpha1",
            )
            self.assertEqual(
                [record["sequence"] for record in records],
                [1, 2, 3, 4, 5],
            )
            self.assertEqual(
                [record["timeout"] for record in records],
                [True, False, True, False, True],
            )


class RuntimeSafetyTests(unittest.TestCase):
    def _spec(self) -> ResearchExperimentSpec:
        return ResearchExperimentSpec(
            campaign_id="campaign-c01",
            run_id="campaign-c01-b01-baseline",
            network_run_id="network-accepted",
            condition="baseline",
            cooja_seed=17,
            sensor_period_seconds=5,
            measurement=MeasurementSpec(duration_seconds=60),
            load=LoadSpec(enabled=False),
            probe_target="192.0.2.1",
        )

    def test_runtime_overrides_restore_accepted_experiment_module_globals(self) -> None:
        import synthran.experiment_runtime as base_runtime

        original_builder = base_runtime.build_scenario
        original_collector = base_runtime.collect_mqtt
        replacement = object()
        with _runtime_overrides(spec=self._spec(), collector=replacement):
            self.assertIs(base_runtime.collect_mqtt, replacement)
            self.assertIsNot(base_runtime.build_scenario, original_builder)
        self.assertIs(base_runtime.build_scenario, original_builder)
        self.assertIs(base_runtime.collect_mqtt, original_collector)

    def test_route_proof_rejects_non_ue_path(self) -> None:
        inventory = object()
        with (
            patch(
                "synthran.research_instrumentation._kubectl_exec_command",
                return_value=("ssh",),
            ),
            patch(
                "synthran.research_instrumentation.base_runtime._run",
                return_value=CommandResult(
                    0,
                    "192.0.2.1 dev eth0 src 10.0.0.2\n",
                    "",
                ),
            ),
        ):
            with self.assertRaisesRegex(Exception, "tun_srsue1"):
                _prove_target_route(
                    inventory,
                    "ue-pod",
                    pdu_address="12.1.0.8",
                    target="192.0.2.1",
                )

    def test_route_proof_accepts_exact_ue_tunnel(self) -> None:
        inventory = object()
        with (
            patch(
                "synthran.research_instrumentation._kubectl_exec_command",
                return_value=("ssh",),
            ),
            patch(
                "synthran.research_instrumentation.base_runtime._run",
                return_value=CommandResult(
                    0,
                    "192.0.2.1 from 12.1.0.8 dev tun_srsue1 src 12.1.0.8\n",
                    "",
                ),
            ),
        ):
            _prove_target_route(
                inventory,
                "ue-pod",
                pdu_address="12.1.0.8",
                target="192.0.2.1",
            )

    def test_cleanup_reproof_requires_persisted_cleanup_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "experiment-evidence.json"
            evidence.write_text(
                json.dumps(
                    {
                        "checks": [
                            {
                                "name": "cleanup-base-network",
                                "passed": True,
                                "detail": "restored",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(_base_cleanup_reproved(root))
            evidence.write_text(
                json.dumps({"checks": []}), encoding="utf-8"
            )
            self.assertFalse(_base_cleanup_reproved(root))


if __name__ == "__main__":
    unittest.main()
