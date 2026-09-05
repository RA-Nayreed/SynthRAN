#!/usr/bin/env python3
"""Render a small, live Ansible progress stream while preserving the full log."""

from __future__ import annotations

import re
import sys


TASK = re.compile(r"^(?:TASK|RUNNING HANDLER) \[(.*?)](?:\s+\*+)?$")
PLAY = re.compile(r"^PLAY \[(.*?)](?:\s+\*+)?$")
ROUTINE_RESULT = re.compile(r"^(ok|changed|skipping|included): \[")


def emit(line: str = "") -> None:
    print(line, flush=True)


def main() -> None:
    hiding_result = False
    hiding_error_detail = False
    retry_reported = False
    pending_play: str | None = None
    pending_task: str | None = None

    def emit_pending() -> None:
        nonlocal pending_play, pending_task
        if pending_play is not None:
            emit(f"\n== {pending_play} ==")
            pending_play = None
        if pending_task is not None:
            emit(f"  -> {pending_task}")
            pending_task = None

    for raw in sys.stdin:
        line = raw.rstrip("\r\n")

        match = PLAY.match(line)
        if match:
            hiding_result = False
            hiding_error_detail = False
            retry_reported = False
            # Do not announce a play until at least one of its tasks actually
            # runs. Ansible still parses plays whose inventory groups are empty.
            pending_play = match.group(1)
            pending_task = None
            continue

        match = TASK.match(line)
        if match:
            hiding_result = False
            hiding_error_detail = False
            retry_reported = False
            # The result tells us whether this task ran or was skipped. Holding
            # the heading prevents inactive core, RAN, and platform choices from
            # appearing in the concise progress stream.
            pending_task = match.group(1)
            continue

        if line.startswith("FAILED - RETRYING:"):
            hiding_result = False
            hiding_error_detail = False
            emit_pending()
            if not retry_reported:
                emit("     waiting for readiness...")
                retry_reported = True
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
            emit_pending()
            emit(f"     ERROR: {line}")
            continue

        if line.startswith(("NO MORE HOSTS LEFT", "PLAY RECAP")):
            hiding_result = False
            pending_play = None
            pending_task = None
            emit(line)
            continue

        if line.startswith(("[WARNING]", "[DEPRECATION WARNING]")):
            hiding_result = False
            emit_pending()
            emit(f"     {line}")
            continue

        match = ROUTINE_RESULT.match(line)
        if match:
            hiding_error_detail = False
            hiding_result = line.endswith("=> {")
            if match.group(1) != "skipping":
                emit_pending()
            continue

        if line.startswith("skipping: no hosts matched"):
            hiding_result = False
            hiding_error_detail = False
            pending_play = None
            pending_task = None
            continue

        if hiding_result or hiding_error_detail or not line.strip():
            continue

        emit_pending()
        emit(line)


if __name__ == "__main__":
    main()
