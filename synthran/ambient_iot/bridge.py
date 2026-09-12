# Copyright 2026 Rezwan Ahmad Nayreed
# SPDX-License-Identifier: Apache-2.0

"""Forward unique generated samples only after authoritative reader decode."""

from __future__ import annotations

import hashlib
import json


def decoded_events(result, scenario):
    prefix = scenario["mqtt"].get("topic_prefix", "synthran")
    requested_bytes = int(scenario["mqtt"].get("payload_bytes", 0))
    names = result["node_names"]
    best = {}
    for behavior in result.get("bs_behaviors", [result["bs_behavior"]]):
        for packet in behavior.rx_packets:
            if (
                packet.collided
                or not packet.matched
                or packet.payload_type != "data"
                or packet.event_id is None
            ):
                continue
            if packet.generated_ms is None or packet.decode_available_ms is None:
                raise ValueError("decoded data lacks generation/decode timing")
            if (
                not packet.generated_ms
                <= packet.start_ms
                <= packet.end_ms
                <= packet.decode_available_ms
            ):
                raise ValueError("invalid generated/transmitted/decoded chronology")
            previous = best.get(packet.event_id)
            if previous is None or (packet.decode_available_ms, -packet.rssi_dbm) < (
                previous.decode_available_ms,
                -previous.rssi_dbm,
            ):
                best[packet.event_id] = packet
    events = []
    for packet in sorted(
        best.values(),
        key=lambda item: (item.decode_available_ms, item.node_id, item.event_id),
    ):
        device = names[packet.node_id]
        generated = round(packet.generated_ms / 1000, 9)
        decoded = round(packet.decode_available_ms / 1000, 9)
        payload = {
            "event_id": packet.event_id,
            "device": device,
            "sequence": packet.sequence,
            "generated_time_s": generated,
            "value": packet.payload,
            "ambient_outcome": packet.outcome,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if requested_bytes:
            missing = requested_bytes - len(encoded.encode("utf-8"))
            if missing < 0:
                raise ValueError(
                    f"payload_bytes={requested_bytes} cannot hold event metadata"
                )
            encoded += " " * missing
        events.append(
            {
                "time_offset_s": decoded,
                "generated_time_s": generated,
                "decode_time_s": decoded,
                "device": device,
                "gateway": scenario["devices"][device].get("gateway", device),
                "sequence": packet.sequence,
                "topic": f"{prefix}/{device}",
                "payload": encoded,
                "payload_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                "event_id": packet.event_id,
                "ambient_iot": {
                    "rssi_dbm": packet.rssi_dbm,
                    "sector_idx": packet.sector_idx,
                    "subcarrier_shift": packet.subcarrier_shift,
                    "outcome": packet.outcome,
                    "decode_stage": packet.decode_stage,
                },
            }
        )
    return events
