"""Translate authoritative Ambient-IoT outcomes into replay events."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from .outcomes import classify


def decoded_events(result: dict[str, Any], scenario: dict[str, Any]) -> list[dict[str, Any]]:
    prefix = scenario["mqtt"].get("topic_prefix", "synthran")
    requested_bytes = int(scenario["mqtt"].get("payload_bytes", 0))
    names = result["node_names"]
    sequences: defaultdict[str, int] = defaultdict(int)
    events: list[dict[str, Any]] = []
    receiver = scenario["model"].get("receiver", {})
    best_packets = {}
    labels = {}
    for behavior in result.get("bs_behaviors", [result["bs_behavior"]]):
        behavior_labels = classify(behavior.rx_packets, float(receiver.get("collision_window_ms", 5)), behavior.enable_sic)
        for packet in behavior.rx_packets:
            labels[id(packet)] = behavior_labels[id(packet)]
            key = (packet.node_id, packet.start_ms, packet.payload)
            current = best_packets.get(key)
            if not packet.collided and packet.matched and (current is None or packet.rssi_dbm > current.rssi_dbm):
                best_packets[key] = packet
    for packet in sorted(best_packets.values(), key=lambda item: (item.start_ms, item.node_id)):
        if packet.collided or not packet.matched:
            continue
        device = names[packet.node_id]
        sequence = sequences[device]
        sequences[device] += 1
        event_id = hashlib.sha256(f"ambient-iot:{device}:{packet.start_ms}:{sequence}".encode()).hexdigest()[:20]
        payload = {
            "event_id": event_id,
            "device": device,
            "sequence": sequence,
            "modeled_time_s": packet.start_ms / 1000.0,
            "value": packet.payload,
            "ambient_outcome": labels[id(packet)],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if requested_bytes > len(encoded.encode()) + 13:
            payload["padding"] = "x" * (requested_bytes - len(encoded.encode()) - 13)
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        events.append(
            {
                "time_offset_s": packet.start_ms / 1000.0,
                "device": device,
                "topic": f"{prefix}/{device}",
                "payload": encoded,
                "event_id": event_id,
                "ambient_iot": {
                    "rssi_dbm": packet.rssi_dbm,
                    "sector_idx": packet.sector_idx,
                    "subcarrier_shift": packet.subcarrier_shift,
                },
            }
        )
    return events
