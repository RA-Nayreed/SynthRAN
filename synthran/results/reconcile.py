from __future__ import annotations
import json
from collections import Counter, defaultdict
from pathlib import Path

def _read(path): return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x]
def reconcile(expected, publisher, broker, output):
    exp, pub, rec = _read(expected), _read(publisher), _read(broker)
    ids = [r["event_id"] for r in rec]; counts = Counter(ids); expected_ids = {r["event_id"] for r in exp}; received = set(ids)
    per_device = defaultdict(lambda: {"expected": 0, "acknowledged": 0, "received": 0, "required_energy_j": 0.0, "available_energy_j": 0.0})
    for r in exp:
        item = per_device[r["device"]]; item["expected"] += 1; item["required_energy_j"] += r.get("required_energy_j", 0.0); item["available_energy_j"] += r.get("available_energy_j", 0.0)
    for r in pub:
        if r.get("acknowledged"): per_device[r["device"]]["acknowledged"] += 1
    for r in rec: per_device[r["device"]]["received"] += 1
    summary = {"expected": len(exp), "emitted": len(pub), "acknowledged": sum(bool(r.get("acknowledged")) for r in pub), "received": len(rec), "missing": sorted(expected_ids - received), "duplicate": {k: v for k, v in counts.items() if v > 1}, "per_device": dict(per_device)}
    Path(output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"); return summary
