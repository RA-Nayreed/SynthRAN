"""Streaming subprocess execution and live progress formatting for Ansible stages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import queue
import re
import subprocess
import threading
from time import monotonic
from typing import Callable, Mapping, Sequence

from synthran.live_preflight import CommandResult


PLAY_RE = re.compile(r"^PLAY\s+\[(.*)\](?:\s*.*)?$")
TASK_RE = re.compile(r"^TASK\s+\[(.*)\](?:\s*.*)?$")
HANDLER_RE = re.compile(r"^RUNNING HANDLER\s+\[(.*)\](?:\s*.*)?$")
HOST_STATUS_RE = re.compile(
    r"^(ok|changed|failed|fatal|skipping|unreachable):\s+\[([^\]]+)\]",
    re.IGNORECASE,
)

STATUS_MAP = {
    "ok": "OK",
    "changed": "CHANGED",
    "failed": "FAILED",
    "fatal": "FATAL",
    "skipping": "SKIPPED",
    "unreachable": "UNREACHABLE",
}


def _clean_ansible_title(raw_name: str) -> str:
    name = raw_name.strip()
    match = re.search(r"(?:\s+|:\s*)[a-zA-Z_][a-zA-Z0-9_]*\s*=", name)
    if match:
        cleaned = name[: match.start()].strip().rstrip(":")
        if cleaned:
            return cleaned.strip()
    return name


def parse_ansible_line(line: str) -> str | None:
    """Parse one raw Ansible line into a sanitized high-level event or None."""
    stripped = line.strip()
    if not stripped:
        return None

    match = PLAY_RE.match(stripped)
    if match:
        name = _clean_ansible_title(match.group(1))
        return f"  PLAY: {name}"

    match = TASK_RE.match(stripped)
    if match:
        name = _clean_ansible_title(match.group(1))
        return f"  TASK: {name}"

    match = HANDLER_RE.match(stripped)
    if match:
        name = _clean_ansible_title(match.group(1))
        return f"  HANDLER: {name}"

    match = HOST_STATUS_RE.match(stripped)
    if match:
        raw_status = match.group(1).lower()
        host = match.group(2).strip()
        status = STATUS_MAP.get(raw_status, raw_status.upper())
        return f"    {host}: {status}"

    return None


def _kill_process_tree(process: subprocess.Popen) -> None:
    """Terminate and reap child process upon timeout or cancellation."""
    try:
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3.0)
    except OSError:
        pass
    finally:
        if process.stdout and not process.stdout.closed:
            try:
                process.stdout.close()
            except OSError:
                pass


def run_streaming_ansible_command(
    command: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str] | None,
    timeout_seconds: int,
    *,
    report: Callable[[str], None] | None = None,
    heartbeat_interval_seconds: float = 30.0,
    poll_interval_seconds: float = 0.5,
) -> CommandResult:
    """Stream sanitized progress for long-running Ansible stages with heartbeats."""
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=dict(environment) if environment is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    output_queue: queue.Queue[str | None] = queue.Queue()

    def _reader() -> None:
        try:
            if process.stdout:
                for line in process.stdout:
                    output_queue.put(line)
        finally:
            output_queue.put(None)
            if process.stdout and not process.stdout.closed:
                try:
                    process.stdout.close()
                except OSError:
                    pass

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    output_lines: list[str] = []
    started = monotonic()
    task_started = started
    next_heartbeat = heartbeat_interval_seconds
    deadline = started + timeout_seconds

    try:
        while True:
            now = monotonic()
            if now > deadline:
                _kill_process_tree(process)
                reader_thread.join(timeout=2.0)
                raise subprocess.TimeoutExpired(
                    cmd=list(command),
                    timeout=timeout_seconds,
                    output="".join(output_lines),
                )

            task_elapsed = now - task_started
            if task_elapsed >= next_heartbeat:
                if report is not None:
                    report(f"  current task still running... {int(next_heartbeat)}s")
                next_heartbeat += heartbeat_interval_seconds

            timeout_to_next = max(0.05, min(poll_interval_seconds, deadline - now))
            try:
                line = output_queue.get(timeout=timeout_to_next)
            except queue.Empty:
                if process.poll() is not None and not reader_thread.is_alive():
                    break
                continue

            if line is None:
                break

            output_lines.append(line)
            if report is not None:
                parsed = parse_ansible_line(line)
                if parsed is not None:
                    report(parsed)
                    if (
                        parsed.startswith("  PLAY:")
                        or parsed.startswith("  TASK:")
                        or parsed.startswith("  HANDLER:")
                    ):
                        task_started = monotonic()
                        next_heartbeat = heartbeat_interval_seconds

        returncode = process.wait()
        reader_thread.join(timeout=2.0)
        return CommandResult(
            returncode=returncode,
            stdout="".join(output_lines),
            stderr="",
        )
    finally:
        if process.stdout and not process.stdout.closed:
            try:
                process.stdout.close()
            except OSError:
                pass
