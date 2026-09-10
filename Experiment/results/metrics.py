"""Application-delivery timing and time-integrated freshness, with explicit validity."""

from __future__ import annotations

import math
import statistics
from datetime import datetime


def epoch(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("measurement timestamps require timezones")
    return parsed.timestamp()


def quantile(values, probability):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def age_process(updates, start, end, limit):
    """Integrate age over a fixed window; unknown initial history remains unknown."""
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError("AoI requires a finite positive observation window")
    if not math.isfinite(limit) or limit < 0:
        raise ValueError("AoI limit must be finite and nonnegative")
    latest, cursor, area, unknown, violation = None, start, 0.0, 0.0, 0.0
    intervals, peaks = [], []

    def interval(left, right, generated):
        if right <= left:
            return 0.0, 0.0, 0.0
        if generated is None:
            return 0.0, right - left, right - left
        lo, hi = left - generated, right - generated
        if lo < -1e-9:
            raise ValueError("generation after reception invalidates physical AoI")
        intervals.append((lo, hi))
        return (
            (lo + hi) * (right - left) / 2,
            0.0,
            max(0.0, right - max(left, generated + limit)),
        )

    for received, generated in sorted(updates):
        if generated > received + 1e-9:
            raise ValueError("generation after reception invalidates physical AoI")
        if received < start:
            latest = generated if latest is None else max(latest, generated)
            continue
        if received >= end:
            break
        additions = interval(cursor, received, latest)
        area += additions[0]
        unknown += additions[1]
        violation += additions[2]
        if latest is None or generated > latest:
            if latest is not None:
                peaks.append(received - latest)
            latest = generated
        cursor = received
    additions = interval(cursor, end, latest)
    area += additions[0]
    unknown += additions[1]
    violation += additions[2]
    initialized = end - start - unknown
    p95 = None
    if initialized > 0:
        left, right = min(lo for lo, _ in intervals), max(hi for _, hi in intervals)
        for _ in range(60):
            middle = (left + right) / 2
            covered = sum(min(max(middle - lo, 0.0), hi - lo) for lo, hi in intervals)
            if covered < 0.95 * initialized:
                left = middle
            else:
                right = middle
        p95 = (left + right) / 2
    return {
        "time_average_aoi_s": area / (end - start) if unknown == 0 else None,
        "initialized_time_average_aoi_s": (
            area / initialized if initialized > 0 else None
        ),
        "initialized_time_p95_aoi_s": p95,
        "uninitialized_fraction": unknown / (end - start),
        "freshness_violation_fraction": violation / (end - start),
        "peak_aoi_p95_s": quantile(peaks, 0.95),
    }


def measurements(
    expected, publisher, receipts, sessions, manifest, contract, collector_records
):
    warmup = float(contract.get("warmup_seconds", 0))
    duration = float(
        manifest.get(
            "duration_seconds",
            max((row["time_offset_s"] for row in expected), default=0) + 1e-6,
        )
    )
    if (
        not math.isfinite(warmup)
        or not math.isfinite(duration)
        or warmup < 0
        or warmup >= duration
    ):
        raise ValueError(
            "measurement warm-up must be shorter than the workload horizon"
        )
    cohort = {
        row["event_id"]: row
        for row in expected
        if warmup <= row["time_offset_s"] < duration
    }
    first_publish, first_receive = {}, {}
    for row in publisher:
        first_publish.setdefault(row["event_id"], row)
    for row in sorted(receipts, key=lambda row: epoch(row["received_utc"])):
        first_receive.setdefault(row["event_id"], row)
    starts = [
        row["start_epoch_ns"] / 1e9 for row in sessions if "start_epoch_ns" in row
    ]
    start = statistics.median(starts) if starts else None
    uncertainty = contract.get("clock_uncertainty_seconds")
    clocks_valid = (
        uncertainty is not None
        and math.isfinite(float(uncertainty))
        and float(uncertainty) >= 0
    )
    if starts and max(starts) - min(starts) > max(float(uncertainty or 0), 1e-6):
        clocks_valid = False
    actual, scheduled, release = [], [], []
    negative_ids = []
    for event_id in cohort:
        sent, received = first_publish.get(event_id), first_receive.get(event_id)
        if sent and "release_error_s" in sent:
            release.append(sent["release_error_s"])
        if not sent or not received:
            continue
        actual_value = epoch(received["received_utc"]) - epoch(sent["sent_utc"])
        if actual_value < 0:
            negative_ids.append(event_id)
            continue
        actual.append(actual_value)
        if "planned_utc" in sent:
            scheduled.append(
                epoch(received["received_utc"]) - epoch(sent["planned_utc"])
            )
    if negative_ids:
        clocks_valid = False
    result = {
        "cohort_events": len(cohort),
        "warmup_seconds": warmup,
        "duration_seconds": duration,
        "clock_contract_satisfied": clocks_valid,
        "clock_evidence_verification": "externally supplied bound; independently verify host synchronization evidence",
        "clock_uncertainty_seconds": uncertainty,
        "negative_latency_event_ids": negative_ids,
        "conditional_receipt_delay_p50_s": quantile(actual, 0.5),
        "conditional_receipt_delay_p95_s": quantile(actual, 0.95),
        "conditional_scheduled_delay_p95_s": quantile(scheduled, 0.95),
        "publisher_release_error_p95_s": quantile(release, 0.95),
    }
    deadline = contract.get("deadline_seconds")
    if deadline is not None:
        deadline = float(deadline)
        if not math.isfinite(deadline) or deadline < 0:
            raise ValueError("deadline_seconds must be finite and nonnegative")
        collector_ends = [
            epoch(row["time_utc"])
            for row in collector_records
            if row.get("record_type") == "collector_end"
        ]
        observed = (
            start is not None
            and bool(collector_ends)
            and max(collector_ends) >= start + duration + deadline
        )
        result["deadline_observation_complete"] = observed
        if start is not None:
            failed = [
                event_id
                for event_id, event in cohort.items()
                if event_id not in first_receive
                or epoch(first_receive[event_id]["received_utc"])
                > start + event["time_offset_s"] + deadline
            ]
            result["deadline_failure_fraction"] = (
                len(failed) / len(cohort)
                if cohort and observed and clocks_valid
                else None
            )
            result["not_observed_by_deadline_event_ids"] = failed
    age_limit = contract.get("age_limit_seconds")
    native = manifest.get("transformation", {}).get("generation_age_valid") is True
    result["physical_aoi_eligible"] = native and clocks_valid and start is not None
    if age_limit is not None and native:
        age_limit = float(age_limit)
        sensors = manifest.get("sensor_gateways", {})
        result["reader_aoi"] = {
            sensor: age_process(
                [
                    (row["decode_time_s"], row["generated_time_s"])
                    for row in expected
                    if row["device"] == sensor
                ],
                warmup,
                duration,
                age_limit,
            )
            for sensor in sensors
        }
        if result["physical_aoi_eligible"]:
            result["application_aoi"] = {
                sensor: age_process(
                    [
                        (
                            epoch(first_receive[row["event_id"]]["received_utc"])
                            - start,
                            row["generated_time_s"],
                        )
                        for row in expected
                        if row["device"] == sensor and row["event_id"] in first_receive
                    ],
                    warmup,
                    duration,
                    age_limit,
                )
                for sensor in sensors
            }
    return result
