# Copyright 2026 Rezwan Ahmad Nayreed
# SPDX-License-Identifier: Apache-2.0

"""Reusable protocol definitions for Ambient-IoT simulations."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from synthran.model.backscatter import BackscatterModule
import math


def _duration(config, key, default):
    value = float(config.get(key, default))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"protocol {key} must be finite and positive")
    return value


def _slots(config, key, default):
    value = config.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"protocol {key} must be a positive integer")
    return value


def broadcast(node_ids: list[int], config: dict[str, Any]) -> list[tuple]:
    """Broadcast polling with framed, randomly selected response slots."""
    tx_ms = _duration(config, "tx_duration_ms", 5)
    rx_ms = _duration(config, "rx_duration_ms", 10)
    slots = _slots(config, "slots", max(1, len(node_ids)))
    return [("tx", tx_ms, "broadcast", {"target": -1, "cmd": "send_data"})] + [
        ("rx", rx_ms, f"slot-{index}") for index in range(slots)
    ]


def unicast(node_ids: list[int], config: dict[str, Any]) -> list[tuple]:
    """Poll each node separately so its response has an exclusive slot."""
    tx_ms = _duration(config, "tx_duration_ms", 5)
    rx_ms = _duration(config, "rx_duration_ms", 10)
    schedule: list[tuple] = []
    for node_id in node_ids:
        schedule.extend(
            [
                (
                    "tx",
                    tx_ms,
                    f"poll-{node_id}",
                    {"target": node_id, "cmd": "send_data"},
                ),
                ("rx", rx_ms, f"reply-{node_id}", {"expect": node_id}),
            ]
        )
    return schedule


def with_registration(
    schedule: list[tuple], node_ids: list[int], config: dict[str, Any]
) -> list[tuple]:
    """Optionally prepend the native ID/ACK registration exchange."""
    if bool(config.get("pre_registered", True)):
        return schedule
    tx_ms = _duration(config, "tx_duration_ms", 5)
    rx_ms = _duration(config, "rx_duration_ms", 10)
    slots = _slots(config, "registration_slots", max(1, len(node_ids)))
    return [
        ("tx", tx_ms, "discover", {"target": -1, "cmd": "send_id"}),
        *(("rx", rx_ms, f"registration-{index}") for index in range(slots)),
        ("tx", tx_ms, "ack", {"target": -1, "cmd": "ack"}),
        *schedule,
    ]


class AdaptiveAlohaNode(BackscatterModule):
    """Ambient-IoT node using an adaptive framed-slotted ALOHA command."""

    def handle_command(self, cmd: str, bs_id: int, data: dict) -> None:
        if cmd != "aloha_frame":
            super().handle_command(cmd, bs_id, data)
            return
        self.state = "registered"
        if self.rx_slots:
            self.chosen_slot_idx = self.rng.randrange(len(self.rx_slots))
            self.last_tx_command_time = self.env.now


def adaptive_aloha(config: dict[str, Any]):
    """Return a policy that adapts frame size from native outcomes."""
    tx_ms = _duration(config, "tx_duration_ms", 5)
    rx_ms = _duration(config, "rx_duration_ms", 10)
    minimum = _slots(config, "min_slots", 2)
    maximum = _slots(config, "max_slots", 128)
    initial = _slots(config, "slots", 16)
    if minimum > maximum:
        raise ValueError("protocol min_slots must not exceed max_slots")

    def policy(bs) -> Iterator[list[tuple]]:
        slots = max(minimum, min(maximum, initial))
        while True:
            yield [("tx", tx_ms, "aloha", {"target": -1, "cmd": "aloha_frame"})] + [
                ("rx", rx_ms, f"slot-{index}") for index in range(slots)
            ]
            heard = bs.slot_outcomes_this_frame.count("success")
            collided = bs.slot_outcomes_this_frame.count("occupied_undecoded")
            if collided > heard:
                slots = min(maximum, slots * 2)
            elif heard < max(1, slots // 4):
                slots = max(minimum, slots // 2)

    return policy


def resolve(name: str, node_ids: list[int], config: dict[str, Any]) -> dict[str, Any]:
    if "schedule" in config:
        schedule = []
        for entry in config["schedule"]:
            if entry["mode"] not in {"rx", "tx"}:
                raise ValueError("custom schedule mode must be rx or tx")
            schedule.append(
                (
                    str(entry["mode"]),
                    _duration(entry, "duration_ms", 10),
                    str(entry["slot_id"]),
                    dict(entry.get("payload", {})),
                )
            )
        if not schedule:
            raise ValueError("custom protocol schedule must not be empty")
        return {"schedule": schedule, "module_class": BackscatterModule}
    normalized = name.lower().replace("-", "_")
    if normalized in {"broadcast", "broadcast_sic", "framed_aloha"}:
        return {
            "schedule": with_registration(
                broadcast(node_ids, config), node_ids, config
            ),
            "module_class": BackscatterModule,
        }
    if normalized == "unicast":
        return {
            "schedule": with_registration(unicast(node_ids, config), node_ids, config),
            "module_class": BackscatterModule,
        }
    if normalized in {"adaptive_aloha", "custom_protocol"}:
        return {"policy": adaptive_aloha(config), "module_class": AdaptiveAlohaNode}
    raise ValueError(f"unsupported Ambient-IoT protocol: {name}")
