from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from synthran.experiment import (
    ExperimentError,
    ExperimentScenario,
    TelemetryEvent,
    append_jsonl,
    append_rejected,
    load_jsonl,
    write_parquet,
)


class MqttCollectorDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = ExperimentScenario(
            "experiment-01",
            "network-accepted-01",
            "12.1.0.1",
        )

    def _record(self, sensor: int, sequence: int) -> dict[str, object]:
        return TelemetryEvent(
            self.scenario.run_id,
            f"sensor-{sensor:02d}",
            sequence,
            sequence * 1000,
            sensor * 1000 + sequence,
        ).to_record(
            received_at_utc=datetime(2026, 8, 16, tzinfo=timezone.utc)
        )

    def test_append_jsonl_is_canonical_and_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "telemetry.jsonl"
            append_jsonl(path, self._record(1, 1))
            records = load_jsonl(path, expected_run_id=self.scenario.run_id)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["sensor_id"], "sensor-01")
            line = path.read_text(encoding="utf-8").strip()
            self.assertEqual(
                line,
                json.dumps(json.loads(line), sort_keys=True, separators=(",", ":")),
            )

    def test_rejected_event_does_not_copy_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rejected.jsonl"
            append_rejected(
                path,
                reason="invalid schema",
                topic="synthran/experiment-01/sensor/sensor-01",
            )
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
        with self.assertRaisesRegex(ExperimentError, "run ID"):
            TelemetryEvent.from_payload(payload, self.scenario.run_id)

    def test_parquet_round_trip_is_typed_and_deterministic(self) -> None:
        try:
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("PyArrow is not installed")
        records = [self._record(2, 2), self._record(1, 2), self._record(1, 1)]
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "telemetry.parquet"
            write_parquet(records, destination)
            table = pq.read_table(destination)
            self.assertEqual(str(table.schema.field("sequence").type), "int64")
            rows = table.to_pylist()
            self.assertEqual(
                [(row["sensor_id"], row["sequence"]) for row in rows],
                [("sensor-01", 1), ("sensor-01", 2), ("sensor-02", 2)],
            )


if __name__ == "__main__":
    unittest.main()
