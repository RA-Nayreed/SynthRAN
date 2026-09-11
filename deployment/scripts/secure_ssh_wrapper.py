#!/usr/bin/env python3
"""Enforce run-scoped SSH host verification for pinned upstream nested SSH calls."""
from __future__ import annotations

import os
import sys


def main() -> None:
    known_hosts = os.environ.get("SYNTHRAN_SSH_KNOWN_HOSTS", "")
    if not known_hosts:
        raise SystemExit("SYNTHRAN_SSH_KNOWN_HOSTS is required")

    source = sys.argv[1:]
    filtered: list[str] = []
    index = 0
    while index < len(source):
        value = source[index]
        if value == "-o" and index + 1 < len(source):
            option = source[index + 1]
            lowered = option.lower()
            if lowered in {
                "stricthostkeychecking=no",
                "userknownhostsfile=/dev/null",
            }:
                index += 2
                continue
            filtered.extend((value, option))
            index += 2
            continue
        lowered = value.lower()
        if lowered in {
            "-ostricthostkeychecking=no",
            "-ouserknownhostsfile=/dev/null",
        }:
            index += 1
            continue
        filtered.append(value)
        index += 1

    argv = [
        "/usr/bin/ssh",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        *filtered,
    ]
    os.execv(argv[0], argv)


if __name__ == "__main__":
    main()
