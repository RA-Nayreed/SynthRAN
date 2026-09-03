"""Reusable protocol definitions for Amber simulations."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from amber.backscatter import BackscatterModule


def broadcast(node_ids: list[int], config: dict[str, Any]) -> list[tuple]:
    """Broadcast polling with framed, randomly selected response slots."""
    tx_ms = int(config.get("tx_duration_ms", 5))
    rx_ms = int(config.get("rx_duration_ms", 10))
    slots = int(config.get("slots", max(1, len(node_ids))))
    return [("tx", tx_ms, "broadcast", {"target": -1, "cmd": "send_data"})] + [
        ("rx", rx_ms, f"slot-{index}") for index in range(slots)
    ]


def unicast(node_ids: list[int], config: dict[str, Any]) -> list[tuple]:
    """Poll each node separately so its response has an exclusive slot."""
    tx_ms = int(config.get("tx_duration_ms", 5))
    rx_ms = int(config.get("rx_duration_ms", 10))
    schedule: list[tuple] = []
    for node_id in node_ids:
        schedule.extend(
            [
                ("tx", tx_ms, f"poll-{node_id}", {"target": node_id, "cmd": "send_data"}),
                ("rx", rx_ms, f"reply-{node_id}", {"expect": node_id}),
            ]
        )
    return schedule


class AdaptiveAlohaNode(BackscatterModule):
    """Amber node using an adaptive framed-slotted ALOHA command."""

    def handle_command(self, cmd: str, bs_id: int, data: dict) -> None:
        if cmd != "aloha_frame":
            super().handle_command(cmd, bs_id, data)
            return
        self.state = "registered"
        if self.rx_slots:
            import random

            self.chosen_slot_idx = random.randrange(len(self.rx_slots))
            self.last_tx_command_time = self.env.now


def adaptive_aloha(config: dict[str, Any]):
    """Return an Amber policy that adapts frame size from native outcomes."""
    tx_ms = int(config.get("tx_duration_ms", 5))
    rx_ms = int(config.get("rx_duration_ms", 10))
    minimum = int(config.get("min_slots", 2))
    maximum = int(config.get("max_slots", 128))
    initial = int(config.get("slots", 16))

    def policy(bs) -> Iterator[list[tuple]]:
        slots = max(minimum, min(maximum, initial))
        while True:
            yield [("tx", tx_ms, "aloha", {"target": -1, "cmd": "aloha_frame"})] + [
                ("rx", rx_ms, f"slot-{index}") for index in range(slots)
            ]
            heard = len(bs.decoded_this_frame)
            collided = sum(1 for packet in bs.rx_packets if packet.collided)
            if collided > heard:
                slots = min(maximum, slots * 2)
            elif heard < max(1, slots // 4):
                slots = max(minimum, slots // 2)

    return policy


def resolve(name: str, node_ids: list[int], config: dict[str, Any]) -> dict[str, Any]:
    normalized = name.lower().replace("-", "_")
    if normalized in {"broadcast", "broadcast_sic", "framed_aloha"}:
        return {"schedule": broadcast(node_ids, config), "module_class": BackscatterModule}
    if normalized == "unicast":
        return {"schedule": unicast(node_ids, config), "module_class": BackscatterModule}
    if normalized in {"adaptive_aloha", "custom_protocol"}:
        return {"policy": adaptive_aloha(config), "module_class": AdaptiveAlohaNode}
    raise ValueError(f"unsupported Amber protocol: {name}")
