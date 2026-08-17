"""Read-only provider access probes and freshness-aware caching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import subprocess
from typing import Callable, Sequence

from synthran.workspace.model import AccessRecord, WorkspaceError, format_utc, utc_now
from synthran.workspace.store import resolve_identity_reference, save_access_record


DEFAULT_ACCESS_REFRESH = timedelta(hours=12)
SLICES_EXPIRY_RE = re.compile(
    r"expires\s+on\s+(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\s+"
    r"(?P<time>[0-9]{2}:[0-9]{2})(?::[0-9]{2})?\s+UTC",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ProbeResult:
    returncode: int
    stdout: str
    stderr: str = ""


Runner = Callable[[Sequence[str], int], ProbeResult]


def subprocess_runner(command: Sequence[str], timeout_seconds: int) -> ProbeResult:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise WorkspaceError(f"required command '{command[0]}' was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceError("provider access probe timed out") from exc
    return ProbeResult(completed.returncode, completed.stdout or "", completed.stderr or "")


def _parse_slices_expiry(output: str) -> datetime | None:
    match = SLICES_EXPIRY_RE.search(output)
    if match is None:
        return None
    return datetime.strptime(
        f"{match.group('date')} {match.group('time')}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=timezone.utc)


def _refresh_boundary(now: datetime, access_until: datetime | None) -> datetime:
    refresh = now + DEFAULT_ACCESS_REFRESH
    if access_until is not None and refresh > access_until:
        refresh = access_until
    return refresh


def verify_slices_project_access(
    *,
    workspace_root: Path,
    username: str,
    project: str,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = 30,
    now: datetime | None = None,
) -> AccessRecord:
    """Verify current SLICES authentication and selected-project membership."""

    current = (now or utc_now()).astimezone(timezone.utc)
    auth = runner(("slices", "auth", "show"), timeout_seconds)
    if auth.returncode != 0:
        raise WorkspaceError("SLICES authentication could not be verified")
    project_result = runner(("slices", "project", "show"), timeout_seconds)
    if project_result.returncode != 0:
        raise WorkspaceError("SLICES project access could not be verified")
    output = "\n".join((project_result.stdout, project_result.stderr))
    if project not in output:
        raise WorkspaceError("active SLICES project does not match the workspace")
    lower = output.lower()
    if "member" not in lower and "membership" not in lower:
        raise WorkspaceError("SLICES project membership was not confirmed")
    access_until = _parse_slices_expiry(output)
    if access_until is not None and current >= access_until:
        raise WorkspaceError("SLICES project access has expired")
    record = AccessRecord(
        provider="slices",
        subject=username,
        scope=project,
        verified_at_utc=format_utc(current),
        refresh_after_utc=format_utc(_refresh_boundary(current, access_until)),
        access_until_utc=(format_utc(access_until) if access_until is not None else None),
        detail="authenticated project membership verified",
    )
    save_access_record(workspace_root, record)
    return record


def verify_r2lab_gateway_access(
    *,
    workspace_root: Path,
    slice_name: str,
    identity_reference: str,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = 30,
    now: datetime | None = None,
) -> AccessRecord:
    """Verify strict public-key authentication to Faraday without checking a lease."""

    current = (now or utc_now()).astimezone(timezone.utc)
    identity = resolve_identity_reference(identity_reference)
    command = (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-i",
        str(identity),
        "--",
        f"{slice_name}@faraday.inria.fr",
        "true",
    )
    result = runner(command, timeout_seconds)
    if result.returncode != 0:
        raise WorkspaceError("R2Lab Faraday public-key access could not be verified")
    record = AccessRecord(
        provider="r2lab",
        subject=slice_name,
        scope="faraday.inria.fr",
        verified_at_utc=format_utc(current),
        refresh_after_utc=format_utc(current + DEFAULT_ACCESS_REFRESH),
        detail="strict public-key gateway access verified",
    )
    save_access_record(workspace_root, record)
    return record
