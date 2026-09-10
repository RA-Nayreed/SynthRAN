"""Conservative packet decoding over actual overlapping airtime intervals."""

from __future__ import annotations

import math


def decode_receptions(
    packets, noise_w, threshold_db, cancellation_factor, enable_sic=True
):
    """Require the SINR threshold throughout each packet, with residual-power SIC."""
    if (
        not 0 <= cancellation_factor <= 1
        or not math.isfinite(noise_w)
        or noise_w <= 0
        or not math.isfinite(threshold_db)
    ):
        raise ValueError("invalid receiver noise or cancellation factor")
    powers = [10 ** ((packet["rssi_dbm"] - 30) / 10) for packet in packets]
    residuals = list(powers)
    candidates = set(range(len(packets)))
    decisions = {}
    decoded = []

    def overlaps(i, j):
        return max(packets[i]["start_ms"], packets[j]["start_ms"]) < min(
            packets[i]["end_ms"], packets[j]["end_ms"]
        )

    def sinr(i):
        packet = packets[i]
        boundaries = {packet["start_ms"], packet["end_ms"]}
        for j, other in enumerate(packets):
            if j != i and overlaps(i, j):
                boundaries.update(
                    (
                        max(packet["start_ms"], other["start_ms"]),
                        min(packet["end_ms"], other["end_ms"]),
                    )
                )
        boundaries = sorted(boundaries)
        maximum = 0.0
        for left, right in zip(boundaries, boundaries[1:]):
            middle = (left + right) / 2
            maximum = max(
                maximum,
                sum(
                    residuals[j]
                    for j, other in enumerate(packets)
                    if j != i and other["start_ms"] <= middle < other["end_ms"]
                ),
            )
        return 10 * math.log10(max(1e-30, powers[i] / (noise_w + maximum))), maximum

    while candidates:
        progressed = False
        for i in sorted(candidates, key=lambda index: (-powers[index], index)):
            packet = packets[i]
            value, interference = sinr(i)
            if packet["end_ms"] <= packet["start_ms"] or not packet.get(
                "energy_complete", True
            ):
                reason = "energy_interrupted"
            elif packet["rssi_dbm"] < packet["sensitivity_dbm"]:
                reason = "below_sensitivity"
            elif value < threshold_db:
                reason = (
                    "collision"
                    if any(overlaps(i, j) for j in range(len(packets)) if j != i)
                    else "below_sinr"
                )
            else:
                cancelled_overlap = (
                    enable_sic
                    and any(overlaps(i, j) for j in decoded)
                    and cancellation_factor > 0
                )
                reason = (
                    ("sic_recovered" if cancelled_overlap else "capture")
                    if any(overlaps(i, j) for j in range(len(packets)) if j != i)
                    else "decoded"
                )
                decisions[i] = {
                    "outcome": reason,
                    "sinr_db": value,
                    "interference_w": interference,
                    "decode_stage": len(decoded),
                    "residual_w": powers[i]
                    * (1 - cancellation_factor if enable_sic else 1),
                }
                decoded.append(i)
                candidates.remove(i)
                residuals[i] = decisions[i]["residual_w"]
                progressed = True
                continue
            decisions[i] = {
                "outcome": reason,
                "sinr_db": value,
                "interference_w": interference,
                "decode_stage": None,
                "residual_w": residuals[i],
            }
        if not progressed:
            break
    return [decisions[i] for i in range(len(packets))]
