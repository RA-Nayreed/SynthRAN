"""Translate authoritative Amber packet outcomes into replay events."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any


def decoded_events(result: dict[str, Any], scenario: dict[str, Any]) -> list[dict[str, Any]]:
    prefix = scenario["mqtt"].get("topic_prefix", "synthran")
    requested_bytes = int(scenario["mqtt"].get("payload_bytes", 0))
    names = result["node_names"]
    sequences: defaultdict[str, int] = defaultdict(int)
    events: list[dict[str, Any]] = []
    for packet in sorted(result["bs_behavior"].rx_packets, key=lambda item: (item.start_ms, item.node_id)):
        if packet.collided or not packet.matched:
            continue
        device = names[packet.node_id]
        sequence = sequences[device]
        sequences[device] += 1
        event_id = hashlib.sha256(f"amber:{device}:{packet.start_ms}:{sequence}".encode()).hexdigest()[:20]
        payload = {
            "event_id": event_id,
            "device": device,
            "sequence": sequence,
            "modeled_time_s": packet.start_ms / 1000.0,
            "value": packet.payload,
            "ambient_outcome": "decoded",
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
                "amber": {
                    "rssi_dbm": packet.rssi_dbm,
                    "sector_idx": packet.sector_idx,
                    "subcarrier_shift": packet.subcarrier_shift,
                },
            }
        )
    return events
