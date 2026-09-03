from __future__ import annotations

import json

from synthran.results import reconcile


def _write(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_reconcile_separates_ambient_and_transport_loss(tmp_path):
    model = tmp_path / "model"
    amber = model / "amber"
    amber.mkdir(parents=True)
    expected = model / "events.jsonl"
    publisher = tmp_path / "publisher.jsonl"
    broker = tmp_path / "broker.jsonl"
    _write(expected, [{"event_id": "a", "device": "node-0"}, {"event_id": "b", "device": "node-0"}])
    _write(publisher, [{"event_id": "a", "device": "node-0", "acknowledged": True}, {"event_id": "b", "device": "node-0", "acknowledged": True}])
    _write(broker, [{"event_id": "a", "device": "node-0"}, {"event_id": "a", "device": "node-0"}])
    (amber / "summary.json").write_text(json.dumps({"opportunities": 5, "transmitted": 3, "decoded": 2}), encoding="utf-8")
    result = reconcile(expected, publisher, broker, tmp_path / "summary.json")
    assert result["ambient_iot"] == {"opportunities": 5, "transmitted": 3, "decoded": 2}
    assert result["five_g"]["input"] == 2
    assert result["five_g"]["received"] == 1
    assert result["five_g"]["transport_lost"] == ["b"]
    assert result["five_g"]["duplicate_receipts"] == 1
