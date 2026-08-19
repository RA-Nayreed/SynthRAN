from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from synthran.research import ResearchError
from synthran.research.instrumentation import _parse_load_log, _start_load_client
from synthran.research.iperf_toolchain import (
    CONTROL_KEEPALIVE_ARG,
    LOCK_KEY,
    UE_IPERF_PATH,
    _locked_spec,
)


class IperfToolchainLockTests(unittest.TestCase):
    def test_research_iperf_is_source_locked_to_321(self) -> None:
        spec = _locked_spec(Path("."))
        self.assertEqual(spec.version, "3.21")
        self.assertEqual(
            spec.sha256,
            "sha256:656e4405ebd620121de7ceca3eaf43a88f79ea1b857d041a6a0b1314801acdd8",
        )
        self.assertEqual(
            spec.url,
            "https://downloads.es.net/pub/iperf/iperf-3.21.tar.gz",
        )
        self.assertIn("iperf-3.21", spec.path)
        self.assertEqual(LOCK_KEY, "iperf3_linux_amd64_source")


class LongUdpRegressionTests(unittest.TestCase):
    def test_udp_result_uses_sender_rate_for_offered_load(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "client.log"
            destination = root / "load.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "end": {
                            "sum_sent": {"bits_per_second": 63_840_000.0},
                            "sum_received": {"bits_per_second": 61_000_000.0},
                            "sum": {"bits_per_second": 61_000_000.0},
                        }
                    }
                ),
                encoding="utf-8",
            )
            _parse_load_log(
                source,
                destination,
                target_bps=63_840_000,
                protocol="udp",
            )
            record = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(record["bits_per_second"], 63_840_000.0)

    def test_broken_pipe_is_invalid_even_when_sender_report_is_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "client.log"
            destination = root / "load.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "error": (
                            "unable to send control message - port may not be available, "
                            "the other side may have stopped running, etc.: Broken pipe"
                        ),
                        "end": {
                            "sum_sent": {"bits_per_second": 36_703_525.7},
                            "sum_received": {"bits_per_second": 0.0},
                            "sum": {"bits_per_second": 36_703_525.7},
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ResearchError, "Broken pipe"):
                _parse_load_log(
                    source,
                    destination,
                    target_bps=63_840_000,
                    protocol="udp",
                )
            self.assertFalse(destination.exists())

    def test_load_client_uses_locked_binary_and_control_keepalive(self) -> None:
        managed = MagicMock()
        with (
            patch(
                "synthran.research.instrumentation._kubectl_exec_command",
                return_value=("ssh", "load"),
            ) as command,
            patch(
                "synthran.research.instrumentation.base_runtime._start_process",
                return_value=managed,
            ),
        ):
            result = _start_load_client(
                inventory=object(),
                ue_pod="ue-pod",
                pdu_address="12.1.0.44",
                target="172.28.2.95",
                port=5220,
                target_bps=63_840_000,
                protocol="udp",
                parallel_flows=2,
                duration_seconds=195,
                repository_root=Path("."),
                log_path=Path("load.log"),
            )
        self.assertIs(result, managed)
        args = command.call_args.args
        self.assertIn(UE_IPERF_PATH, args)
        self.assertIn(CONTROL_KEEPALIVE_ARG, args)
        self.assertIn("-u", args)
        self.assertIn("-P", args)


if __name__ == "__main__":
    unittest.main()
