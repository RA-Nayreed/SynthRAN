"""Persist native Amber evidence and SynthRAN bridge outputs."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .bridge import decoded_events
from .outcomes import classify


def _jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def write(result: dict[str, Any], scenario: dict[str, Any], destination: Path) -> dict[str, Any]:
    amber_dir = destination / "amber"
    capacitor_dir = amber_dir / "capacitor"
    capacitor_dir.mkdir(parents=True, exist_ok=True)
    names = result["node_names"]
    behaviors = result.get("bs_behaviors", [result["bs_behavior"]])
    receiver = scenario["model"].get("receiver", {})
    rx = []
    bs_tx = []
    for behavior in behaviors:
        labels = classify(behavior.rx_packets, float(receiver.get("collision_window_ms", 5)), behavior.enable_sic)
        rx.extend({**asdict(packet), "outcome": labels[id(packet)]} for packet in behavior.rx_packets)
        bs_tx.extend({"bs_id": behavior.id, **asdict(packet)} for packet in behavior.tx_packets)
    node_tx = []
    node_rx = []
    for module in result["backscatter_modules"]:
        node_tx.extend({"node_id": module.node.id, **asdict(record)} for record in module.tx_records)
        node_rx.extend({"node_id": module.node.id, **asdict(record)} for record in module.rx_records)
    _jsonl(amber_dir / "bs-rx.jsonl", rx)
    _jsonl(amber_dir / "bs-tx.jsonl", bs_tx)
    _jsonl(amber_dir / "node-tx.jsonl", node_tx)
    _jsonl(amber_dir / "node-rx.jsonl", node_rx)
    controller_rows = [
        {
            "node_id": item.id,
            "device": names[item.id],
            "state": item.state_name,
            "active": item.is_active,
            "data_cycles": len(item.data_history),
        }
        for item in result["controllers"]
    ]
    _jsonl(amber_dir / "controller.jsonl", controller_rows)
    _jsonl(amber_dir / "transitions.jsonl", result["controller_transitions"])
    topology = {
        "nodes": [{"id": node.id, "device": names[node.id], "x": node.x, "y": node.y, "height_m": node.height} for node in result["nodes"]],
        "base_stations": [{"id": item.id, "x": item.x, "y": item.y} for item in result["base_stations"]],
    }
    (amber_dir / "topology.json").write_text(json.dumps(topology, indent=2), encoding="utf-8")
    coverage = {key: value for key, value in result["downlink"].items() if key != "per_node_powers"}
    (amber_dir / "coverage.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    for cap in result["capacitors"]:
        with (capacitor_dir / f"{names[cap.id]}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_s", "voltage_v"])
            writer.writerows(cap.voltage_history)
    events = decoded_events(result, scenario)
    attempted = sum(module.packets_sent for module in result["backscatter_modules"])
    opportunities = {node_id: 0 for node_id in names}
    # All BSs use the same protocol clock; the first BS defines experiment
    # opportunities while every BS contributes independent RX evidence.
    for packet in behaviors[0].tx_packets:
        if packet.cmd not in {"send_data", "aloha_frame"}:
            continue
        targets = names if packet.target_node == -1 else [packet.target_node]
        for node_id in targets:
            opportunities[node_id] += 1
    suppressed = []
    for module in result["backscatter_modules"]:
        missing = max(0, opportunities[module.node.id] - module.packets_sent)
        suppressed.extend(
            {
                "device": names[module.node.id],
                "reason": "amber_energy_or_protocol_suppressed",
                "opportunity_index": index,
            }
            for index in range(missing)
        )
    summary = {
        "engine": "amber",
        "duration_ms": result["environment"].now,
        "transmitted": attempted,
        "opportunities": sum(opportunities.values()),
        "energy_or_protocol_suppressed": len(suppressed),
        "received": len(rx),
        "decoded": len(events),
        "radio_collision_loss": sum(1 for behavior in behaviors for packet in behavior.rx_packets if packet.collided),
        "below_sensitivity_or_unheard": max(0, attempted - len(rx)),
        "sic_enabled": any(behavior.enable_sic for behavior in behaviors),
        "base_stations": len(behaviors),
    }
    (amber_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    manifest = {"engine": "amber", "source": "third_party/amber/SOURCE.json", "seed": scenario["model"].get("seed", 1), "protocol": scenario["model"].get("protocol", {}).get("type", "broadcast")}
    (destination / "amber-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"events": events, "suppressed": suppressed, "summary": summary}
