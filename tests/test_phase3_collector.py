from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile
import unittest

from synthran.phase3_runtime import (
    Phase3Error,
    Phase3Scenario,
    TelemetryEvent,
    append_jsonl,
    append_rejected,
    load_jsonl,
)


class Phase3CollectorDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = Phase3Scenario(
            "phase3-01",
            "acceptance-20260815-05",
            "12.1.0.1",
        )

    def test_append_jsonl_is_canonical_and_loadable(self) -> None:
        event = TelemetryEvent(
            self.scenario.run_id,
            "sensor-01",
            1,
            1000,
            1001,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "telemetry.jsonl"
            append_jsonl(
                path,
                event.to_record(
                    received_at_utc=datetime(2026, 8, 16, tzinfo=timezone.utc)
                ),
            )
            records = load_jsonl(path, expected_run_id=self.scenario.run_id)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["sensor_id"], "sensor-01")
            line = path.read_text(encoding="utf-8").strip()
            self.assertEqual(line, json.dumps(json.loads(line), sort_keys=True, separators=(",", ":")))

    def test_rejected_event_does_not_copy_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rejected.jsonl"
            append_rejected(path, reason="invalid schema", topic="synthran/run/sensor/sensor-01")
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value["reason"], "invalid schema")
            self.assertNotIn("payload", value)

    def test_payload_from_another_run_is_rejected(self) -> None:
        payload = json.dumps(
            {
                "schema": "synthran/telemetry/v1alpha1",
                "run_id": "other-run",
                "sensor_id": "sensor-01",
                "sequence": 1,
                "sensor_time_ms": 0,
                "value_milli": 1001,
            }
        )
        with self.assertRaisesRegex(Phase3Error, "run ID"):
            TelemetryEvent.from_payload(payload, self.scenario.run_id)


if __name__ == "__main__":
    unittest.main()
