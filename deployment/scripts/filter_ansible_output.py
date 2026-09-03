#!/usr/bin/env python3
"""Render a small, live Ansible progress stream while preserving the full log."""

from __future__ import annotations

import re
import sys


TASK = re.compile(r"^(?:TASK|RUNNING HANDLER) \[(.*?)](?:\s+\*+)?$")
PLAY = re.compile(r"^PLAY \[(.*?)](?:\s+\*+)?$")
ROUTINE_RESULT = re.compile(r"^(?:ok|changed|skipping|included): \[")


def emit(line: str = "") -> None:
    print(line, flush=True)


def main() -> None:
    hiding_result = False
    hiding_error_detail = False
    for raw in sys.stdin:
        line = raw.rstrip("\r\n")

        match = PLAY.match(line)
        if match:
            hiding_result = False
            hiding_error_detail = False
            emit(f"\n== {match.group(1)} ==")
            continue

        match = TASK.match(line)
        if match:
            hiding_result = False
            hiding_error_detail = False
            emit(f"  -> {match.group(1)}")
            continue

        if line.startswith("FAILED - RETRYING:"):
            hiding_result = False
            hiding_error_detail = False
            emit("     retry:" + line.removeprefix("FAILED - RETRYING:"))
            continue

        # Newer Ansible versions emit an [ERROR] diagnostic even when a task's
        # failed_when expression deliberately converts the result to success.
        # A following fatal: result is the authoritative terminal failure.
        if line.startswith("[ERROR]"):
            hiding_error_detail = True
            continue

        if line.startswith("fatal:") or "UNREACHABLE!" in line:
            hiding_result = False
            hiding_error_detail = False
            emit(f"     ERROR: {line}")
            continue

        if line.startswith(("NO MORE HOSTS LEFT", "PLAY RECAP")):
            hiding_result = False
            emit(line)
            continue

        if line.startswith(("[WARNING]", "[DEPRECATION WARNING]")):
            hiding_result = False
            emit(f"     {line}")
            continue

        if ROUTINE_RESULT.match(line):
            hiding_error_detail = False
            hiding_result = line.endswith("=> {")
            continue

        if hiding_result or hiding_error_detail or not line.strip():
            continue

        emit(line)


if __name__ == "__main__":
    main()
