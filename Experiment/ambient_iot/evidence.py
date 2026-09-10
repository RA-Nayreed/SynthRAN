"""Persist native Ambient-IoT evidence and bridge outputs."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .bridge import decoded_events


def _jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def write(
    result: dict[str, Any], scenario: dict[str, Any], destination: Path
) -> dict[str, Any]:
    evidence_dir = destination / "ambient_iot"
    capacitor_dir = evidence_dir / "capacitor"
    capacitor_dir.mkdir(parents=True, exist_ok=True)
    names = result["node_names"]
    behaviors = result.get("bs_behaviors", [result["bs_behavior"]])
    rx = []
    bs_tx = []
    for behavior in behaviors:
        rx.extend(asdict(packet) for packet in behavior.rx_packets)
        bs_tx.extend(
            {"bs_id": behavior.id, **asdict(packet)} for packet in behavior.tx_packets
        )
    node_tx = []
    node_rx = []
    for module in result["backscatter_modules"]:
        node_tx.extend(
            {"node_id": module.node.id, **asdict(record)}
            for record in module.tx_records
        )
        node_rx.extend(
            {"node_id": module.node.id, **asdict(record)}
            for record in module.rx_records
        )
    _jsonl(evidence_dir / "bs-rx.jsonl", rx)
    _jsonl(evidence_dir / "bs-tx.jsonl", bs_tx)
    _jsonl(evidence_dir / "node-tx.jsonl", node_tx)
    _jsonl(evidence_dir / "node-rx.jsonl", node_rx)
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
    _jsonl(evidence_dir / "controller.jsonl", controller_rows)
    _jsonl(evidence_dir / "transitions.jsonl", result["controller_transitions"])
    _jsonl(
        evidence_dir / "sample-events.jsonl",
        sorted(
            (row for controller in result["controllers"] for row in controller.events),
            key=lambda row: (row["time_ms"], row["node_id"]),
        ),
    )
    _jsonl(
        evidence_dir / "sensing-opportunities.jsonl",
        sorted(
            (
                row
                for controller in result["controllers"]
                for row in controller.opportunities
            ),
            key=lambda row: (row["time_ms"], row["node_id"]),
        ),
    )
    energy_accounts = [
        {
            "node_id": cap.id,
            "initial_j": cap.initial_energy,
            "stored_j": cap.energy,
            "elapsed_s": cap.internal_time,
            **cap.energy_account,
            "always_powered_supply_j": controller.supplied_energy_j,
        }
        for cap, controller in zip(result["capacitors"], result["controllers"])
    ]
    _jsonl(evidence_dir / "energy-accounting.jsonl", energy_accounts)
    sources_dir = evidence_dir / "energy-inputs"
    sources_dir.mkdir(exist_ok=True)
    for node_id, source in result["energy_sources"].items():
        with (sources_dir / f"{names[node_id]}.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_s", "power_w"])
            writer.writerows(zip(source.times_s, source.values))
    topology = {
        "nodes": [
            {
                "id": node.id,
                "device": names[node.id],
                "x": node.x,
                "y": node.y,
                "height_m": node.height,
            }
            for node in result["nodes"]
        ],
        "base_stations": [
            {"id": item.id, "x": item.x, "y": item.y}
            for item in result["base_stations"]
        ],
    }
    (evidence_dir / "topology.json").write_text(
        json.dumps(topology, indent=2), encoding="utf-8"
    )
    coverage = {
        key: value
        for key, value in result["downlink"].items()
        if key != "per_node_powers"
    }
    (evidence_dir / "coverage.json").write_text(
        json.dumps(coverage, indent=2), encoding="utf-8"
    )
    for cap in result["capacitors"]:
        with (capacitor_dir / f"{names[cap.id]}.csv").open(
            "w", encoding="utf-8", newline=""
        ) as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_s", "voltage_v"])
            writer.writerows(cap.voltage_history)
    events = decoded_events(result, scenario)
    attempted = sum(module.packets_sent for module in result["backscatter_modules"])
    opportunities = [
        row for item in result["controllers"] for row in item.opportunities
    ]
    suppressed = [
        {
            "device": names[row["node_id"]],
            "time_offset_s": row["time_ms"] / 1000,
            "reason": (
                "incomplete_at_horizon"
                if row["outcome"] == "sensing_started"
                else row["outcome"]
            ),
            "opportunity_index": row["opportunity_index"],
        }
        for row in opportunities
        if row["outcome"] != "generated"
    ]
    received_attempts = {}
    for packet in rx:
        key = (packet["node_id"], packet["start_ms"])
        received_attempts.setdefault(key, []).append(packet)
    collision_losses = sum(
        all(packet["outcome"] == "collision" for packet in packets)
        for packets in received_attempts.values()
    )
    sensitivity_losses = sum(
        all(packet["outcome"] == "below_sensitivity" for packet in packets)
        for packets in received_attempts.values()
    )
    unresolved = {
        (row["node_id"], row["start_ms"]) for row in node_tx
    } - received_attempts.keys()
    buffered = {
        (row["node_id"], row["transmission"]["start_ms"])
        for behavior in behaviors
        for row in behavior._rx_buffer
    }
    unfinished = {
        (row["node_id"], row["start_ms"])
        for row in node_tx
        if row["end_ms"] >= result["environment"].now
    }
    censored = unresolved & (buffered | unfinished)
    summary = {
        "engine": "ambient_iot",
        "duration_ms": result["environment"].now,
        "transmitted": attempted,
        "opportunities": len(opportunities),
        "generated": sum(len(item.data_history) for item in result["controllers"]),
        "energy_or_protocol_suppressed": len(suppressed),
        "received": len(rx),
        "decoded": len(events),
        "radio_collision_loss": collision_losses,
        "below_sensitivity_or_unheard": len(unresolved - censored) + sensitivity_losses,
        "receiver_attempts_censored_at_horizon": len(censored),
        "receiver_failures_by_reason": dict(
            Counter(packet["outcome"] for packet in rx if packet["collided"])
        ),
        "sic_enabled": any(behavior.enable_sic for behavior in behaviors),
        "base_stations": len(behaviors),
        "sensors": len(names),
        "gateways": len({device["gateway"] for device in scenario["devices"].values()}),
        "receiver_abstraction": "minimum instantaneous SINR across packet airtime; residual-power SIC",
        "command_abstraction": "power/state-gated command at scheduled command start; listening load while waiting",
    }
    (evidence_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    manifest = {
        "engine": "ambient_iot",
        "lineage": "third_party/amber/SOURCE.json",
        "seed": scenario["model"].get("seed", 1),
        "protocol": scenario["model"].get("protocol", {}).get("type", "broadcast"),
    }
    (destination / "ambient-iot-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return {"events": events, "suppressed": suppressed, "summary": summary}
