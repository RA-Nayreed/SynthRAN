#!/usr/bin/env python3
"""Regression checks for safe multi-node POS fresh preparation."""

from __future__ import annotations

import os
import subprocess
from typing import Any

from synthran import reservation


class CheckError(RuntimeError):
    pass


def done(argv: list[str], rc: int = 0, out: str = "", err: str = ""):
    return subprocess.CompletedProcess(list(argv), rc, out, err)


class Fake:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[list[str]] = []

    def __call__(self, argv, *, check=True, stdin=None):
        command = list(argv)
        self.calls.append(command)
        result = self.handler(command, len(self.calls))
        if check and result.returncode:
            detail = reservation._output(result) or str(result.returncode)
            raise reservation.ReservationError(
                f"command failed: {' '.join(command)}\n{detail}"
            )
        return result


def assert_no_destructive_host_mutation(calls: list[list[str]]) -> None:
    forbidden = (
        ["pos", "allocations", "free", "-k"],
        ["pos", "nodes", "image"],
        ["pos", "nodes", "bootparameter"],
        ["pos", "nodes", "reset"],
    )
    for command in calls:
        if any(command[: len(prefix)] == prefix for prefix in forbidden):
            raise CheckError(f"destructive command ran before all allocation probes succeeded: {command}")


def failed_second_probe_is_non_destructive() -> None:
    selected = ["sopnode-f2", "sopnode-f3"]

    def handler(argv: list[str], _n: int):
        if argv == ["pos", "allocations", "allocate", "sopnode-f2"]:
            return done(argv, rc=1, out="Nodes are already allocated: sopnode-f2")
        if argv == ["pos", "allocations", "allocate", "sopnode-f3"]:
            return done(argv, rc=7, err="provider allocation failure")
        raise CheckError(f"unexpected command after failed probe: {argv}")

    fake = Fake(handler)
    original = reservation.run
    reservation.run = fake
    try:
        try:
            reservation.prepare_hosts(
                {"host_preparation": "fresh", "image": "configured-image"},
                selected=selected,
                calendar={"status": "reused"},
            )
        except reservation.ReservationError as exc:
            if "provider allocation failure" not in str(exc):
                raise CheckError(f"unexpected failure: {exc}") from exc
        else:
            raise CheckError("expected second allocation probe to fail")
    finally:
        reservation.run = original

    expected = [
        ["pos", "allocations", "allocate", "sopnode-f2"],
        ["pos", "allocations", "allocate", "sopnode-f3"],
    ]
    if fake.calls != expected:
        raise CheckError(f"unexpected probe sequence: {fake.calls}")
    assert_no_destructive_host_mutation(fake.calls)


def all_nodes_are_probed_before_reclaim_or_image() -> None:
    selected = ["sopnode-f2", "sopnode-f3"]
    first_f2 = True

    def handler(argv: list[str], _n: int):
        nonlocal first_f2
        if argv == ["pos", "allocations", "allocate", "sopnode-f2"] and first_f2:
            first_f2 = False
            return done(argv, rc=1, out="Nodes are already allocated: sopnode-f2")
        if argv[:3] == ["pos", "allocations", "allocate"]:
            return done(argv, out=f"Allocation ID: ci-{argv[-1]}")
        if argv[:4] == ["pos", "allocations", "free", "-k"]:
            return done(argv)
        if argv[:3] in (
            ["pos", "nodes", "image"],
            ["pos", "nodes", "bootparameter"],
            ["pos", "nodes", "reset"],
        ):
            return done(argv)
        if argv and argv[0] == "ssh":
            return done(argv)
        raise CheckError(f"unexpected command: {argv}")

    fake = Fake(handler)
    original = reservation.run
    old_attempts = os.environ.get("SYNTHRAN_POS_READY_ATTEMPTS")
    old_interval = os.environ.get("SYNTHRAN_POS_READY_INTERVAL_SECONDS")
    os.environ["SYNTHRAN_POS_READY_ATTEMPTS"] = "1"
    os.environ["SYNTHRAN_POS_READY_INTERVAL_SECONDS"] = "0"
    reservation.run = fake
    try:
        result = reservation.prepare_hosts(
            {"host_preparation": "fresh", "image": "configured-image"},
            selected=selected,
            calendar={"status": "reused"},
        )
    finally:
        reservation.run = original
        if old_attempts is None:
            os.environ.pop("SYNTHRAN_POS_READY_ATTEMPTS", None)
        else:
            os.environ["SYNTHRAN_POS_READY_ATTEMPTS"] = old_attempts
        if old_interval is None:
            os.environ.pop("SYNTHRAN_POS_READY_INTERVAL_SECONDS", None)
        else:
            os.environ["SYNTHRAN_POS_READY_INTERVAL_SECONDS"] = old_interval

    if result["nodes"]["sopnode-f2"]["allocation"] != "reclaimed":
        raise CheckError("sopnode-f2 should be recorded as reclaimed")
    if result["nodes"]["sopnode-f3"]["allocation"] != "new":
        raise CheckError("sopnode-f3 should be recorded as newly allocated")

    probe_f2 = fake.calls.index(["pos", "allocations", "allocate", "sopnode-f2"])
    probe_f3 = fake.calls.index(["pos", "allocations", "allocate", "sopnode-f3"])
    reclaim_f2 = fake.calls.index(["pos", "allocations", "free", "-k", "sopnode-f2"])
    first_image = next(
        index for index, command in enumerate(fake.calls)
        if command[:3] == ["pos", "nodes", "image"]
    )
    if not (probe_f2 < probe_f3 < reclaim_f2 < first_image):
        raise CheckError(f"two-phase ordering regressed: {fake.calls}")


def main() -> int:
    failed_second_probe_is_non_destructive()
    all_nodes_are_probed_before_reclaim_or_image()
    print("POS multi-node preparation regression checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
