"""Regression tests for the Experiment-2 cross-host clock contract."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Experiments.Ex2_Flagship_Causal_5G_Transport import runtime


class ClockContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = {
            "deployment": {
                "platform": "r2lab",
                "nodes": {"broker": "sopnode-f2", "ran": "sopnode-f3"},
            },
            "bindings": [
                {"device": "qhat01", "host": "qhat01"},
                {"device": "qhat03", "host": "qhat03"},
            ],
        }

    @staticmethod
    def interval(host: str, *, synchronized: bool = True) -> dict:
        if host == "qhat01":
            lower, upper = -0.002, 0.003
        else:
            lower, upper = -0.001, 0.002
        return {
            "host": host,
            "rtt_seconds": 0.004,
            "offset_lower_seconds": lower,
            "offset_upper_seconds": upper,
            "ntp_synchronized": synchronized,
        }

    def test_synchronized_endpoints_produce_valid_retained_contract(self) -> None:
        with patch.object(
            runtime,
            "_clock_interval",
            side_effect=lambda _environment, host: self.interval(host),
        ):
            record = runtime._clock_evidence(self.root, self.environment, "session1")

        self.assertTrue(record["contract_satisfied"])
        self.assertGreaterEqual(record["clock_uncertainty_seconds"], 0)
        retained = json.loads((self.root / "clock/session1.json").read_text())
        self.assertEqual(retained["schema_version"], 2)
        self.assertTrue(retained["publisher"]["ntp_synchronized"])
        self.assertTrue(retained["broker"]["ntp_synchronized"])

    def test_unsynchronized_endpoint_is_retained_then_blocks_timing_run(self) -> None:
        def fake_interval(_environment, host):
            return self.interval(host, synchronized=host != "qhat01")

        with (
            patch.object(runtime, "_clock_interval", side_effect=fake_interval),
            self.assertRaisesRegex(RuntimeError, "clock contract failed"),
        ):
            runtime._clock_evidence(self.root, self.environment, "qualification")

        retained = json.loads((self.root / "clock/qualification.json").read_text())
        self.assertFalse(retained["contract_satisfied"])
        self.assertFalse(retained["publisher"]["ntp_synchronized"])

    def test_cached_failed_contract_remains_blocking(self) -> None:
        path = self.root / "clock/session2.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "clock_uncertainty_seconds": 0.01,
                    "publisher": {"ntp_synchronized": True},
                    "broker": {"ntp_synchronized": False},
                    "contract_satisfied": False,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "clock contract failed"):
            runtime._clock_evidence(self.root, self.environment, "session2")


if __name__ == "__main__":
    unittest.main()
