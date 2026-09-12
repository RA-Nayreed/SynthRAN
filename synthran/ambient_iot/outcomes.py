# Copyright 2026 Rezwan Ahmad Nayreed
# SPDX-License-Identifier: Apache-2.0

"""Read receiver decisions without reconstructing collision or cancellation stages."""
from __future__ import annotations


def classify(packets, collision_window_ms=None, sic_enabled=None):
    return {id(packet): packet.outcome for packet in packets}
