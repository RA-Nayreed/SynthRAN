#!/usr/bin/env python3
"""Regression checks for reuse of an active exact POS reservation.

Physical validation on 2026-09-16 exposed a rolling-duration bug: a 120-minute
reservation stopped qualifying for reuse as soon as wall-clock time elapsed, so
SynthRAN attempted to create an overlapping reservation and POS returned -1.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from typing import Any

from synthran import reservation


class CheckError(RuntimeError):
    pass


def done(argv: list[str], rc: int = 0, out: str = "", err: str = ""):
    return subprocess.CompletedProcess(argv, rc, out, err)


class CalendarOnlyFake:
    def __init__(self, events: list[dict[str, Any]]):
        self.events = events
        self.calls: list[list[str]] = []

    def __call__(self, argv, *, check=True, stdin=None):
        command = list(argv)
        self.calls.append(command)
        if command == ["pos", "calendar", "list", "--json"]:
            return done(command, out=json.dumps(self.events))
        if command[:3] == ["pos", "calendar", "create"]:
            raise CheckError(f"active exact reservation triggered overlapping create: {command}")
        raise CheckError(f"unexpected command: {command}")


def event(
    event_id: str,
    *,
    start: dt.datetime,
    duration_minutes: int,
    nodes: list[str],
) -> dict[str, Any]:
    return {
        "id": event_id,
        "owner": "ci-user",
        "nodes": nodes,
        "start_date": start.isoformat(),
        "end_date": (start + dt.timedelta(minutes=duration_minutes)).isoformat(),
    }


def expect_error(call, needle: str) -> None:
    try:
        call()
    except reservation.ReservationError as exc:
        if needle not in str(exc):
            raise CheckError(f"expected {needle!r}, got {str(exc)!r}") from exc
        return
    raise CheckError(f"expected ReservationError containing {needle!r}")


def main() -> int:
    original = reservation.run
    tz = dt.timezone(dt.timedelta(hours=2))
    # Mirrors physical event 6536: booked for 120 minutes, rerun 7 minutes later.
    start = dt.datetime(2026, 9, 16, 10, 10, tzinfo=tz)
    now = start + dt.timedelta(minutes=7)
    selected = ["sopnode-f3", "sopnode-f2"]

    try:
        active_120 = event("6536", start=start, duration_minutes=120, nodes=selected)
        fake = CalendarOnlyFake([active_120])
        reservation.run = fake
        record = reservation.acquire_calendar(
            {"mode": "create", "duration_minutes": 120},
            selected=selected,
            owner="ci-user",
            now=now,
        )
        if record["status"] != "reused" or record["id"] != "6536":
            raise CheckError(f"unexpected reuse record: {record}")
        if any(call[:3] == ["pos", "calendar", "create"] for call in fake.calls):
            raise CheckError("create mode attempted a second overlapping reservation")

        # require-existing remains a remaining-coverage promise. Seven elapsed
        # minutes means this same event no longer covers a fresh 120-minute window.
        strict = CalendarOnlyFake([active_120])
        reservation.run = strict
        expect_error(
            lambda: reservation.acquire_calendar(
                {"mode": "require-existing", "duration_minutes": 120},
                selected=selected,
                owner="ci-user",
                now=now,
            ),
            "requested duration",
        )
        if any(call[:3] == ["pos", "calendar", "create"] for call in strict.calls):
            raise CheckError("require-existing attempted a mutation")

        # An active event booked for less than the configured acquisition duration
        # must fail closed rather than being silently accepted or overlapped.
        short = CalendarOnlyFake(
            [event("short", start=start, duration_minutes=60, nodes=selected)]
        )
        reservation.run = short
        expect_error(
            lambda: reservation.acquire_calendar(
                {"mode": "create", "duration_minutes": 120},
                selected=selected,
                owner="ci-user",
                now=now,
            ),
            "shorter than requested",
        )
        if any(call[:3] == ["pos", "calendar", "create"] for call in short.calls):
            raise CheckError("short active reservation triggered overlapping create")
    finally:
        reservation.run = original

    print("POS calendar reuse regression: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
