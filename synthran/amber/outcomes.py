"""Classify native Amber RX decisions without recalculating reception."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def classify(packets: list[Any], collision_window_ms: float, sic_enabled: bool) -> dict[int, str]:
    """Label packets after Amber has authoritatively set ``collided``.

    Grouping is used only to distinguish capture and SIC recovery among packets
    Amber already decoded. It never changes Amber's success/failure decision.
    """
    labels: dict[int, str] = {}
    grouped: defaultdict[int, list[Any]] = defaultdict(list)
    for packet in packets:
        grouped[int(packet.subcarrier_shift)].append(packet)
    for candidates in grouped.values():
        candidates.sort(key=lambda packet: packet.start_ms)
        used: set[int] = set()
        for index, packet in enumerate(candidates):
            if index in used:
                continue
            group = [other for other in range(index, len(candidates)) if abs(candidates[other].start_ms - packet.start_ms) <= collision_window_ms]
            used.update(group)
            members = [candidates[item] for item in group]
            if len(members) == 1:
                labels[id(packet)] = "decoded" if not packet.collided else "collision"
                continue
            decoded = sorted((item for item in members if not item.collided), key=lambda item: item.rssi_dbm, reverse=True)
            for item in members:
                if item.collided:
                    labels[id(item)] = "collision"
                elif item is decoded[0]:
                    labels[id(item)] = "capture"
                else:
                    labels[id(item)] = "sic_recovered" if sic_enabled else "capture"
    return labels
