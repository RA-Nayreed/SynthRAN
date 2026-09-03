"""Reconcile Ambient-IoT model output with 5G/MQTT delivery evidence."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def _read(path: str | Path) -> list[dict]:
    source = Path(path)
    if not source.exists():
        return []
    return [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]


def reconcile(expected, publisher, broker, output="summary.json") -> dict:
    expected_rows = _read(expected)
    publisher_rows = _read(publisher)
    broker_rows = _read(broker)
    expected_ids = {row["event_id"] for row in expected_rows}
    published_ids = {row["event_id"] for row in publisher_rows}
    received_counts = Counter(row["event_id"] for row in broker_rows)
    received_ids = set(received_counts)
    acknowledged_ids = {row["event_id"] for row in publisher_rows if row.get("acknowledged")}
    devices = sorted({row.get("device", "unknown") for row in expected_rows})
    per_device = {}
    for device in devices:
        model_ids = {row["event_id"] for row in expected_rows if row.get("device") == device}
        per_device[device] = {
            "ambient_iot_decoded": len(model_ids),
            "published": len(model_ids & published_ids),
            "broker_received": len(model_ids & received_ids),
            "transport_lost": len((model_ids & published_ids) - received_ids),
        }
    ambient_summary_path = Path(expected).parent / "ambient_iot" / "summary.json"
    ambient = json.loads(ambient_summary_path.read_text(encoding="utf-8")) if ambient_summary_path.exists() else {"decoded": len(expected_ids)}
    summary = {
        "ambient_iot": ambient,
        "five_g": {
            "input": len(expected_ids),
            "published": len(expected_ids & published_ids),
            "acknowledged": len(expected_ids & acknowledged_ids),
            "received": len(expected_ids & received_ids),
            "publisher_missing": sorted(expected_ids - published_ids),
            "transport_lost": sorted((expected_ids & published_ids) - received_ids),
            "unexpected_received": sorted(received_ids - expected_ids),
            "duplicate_receipts": sum(max(0, count - 1) for count in received_counts.values()),
        },
        "per_device": per_device,
    }
    Path(output).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
