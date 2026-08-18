"""Read-only provider access probes and freshness-aware caching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import subprocess
from typing import Callable, Sequence

from synthran.workspace.model import AccessRecord, WorkspaceError, format_utc, utc_now
from synthran.workspace.store import (
    load_access_record,
    resolve_identity_reference,
    save_access_record,
    ssh_identity_fingerprint,
)


DEFAULT_ACCESS_REFRESH = timedelta(hours=12)
SLICES_EXPIRY_RE = re.compile(
    r"expires\s+on\s+(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\s+"
    r"(?P<time>[0-9]{2}:[0-9]{2})(?::[0-9]{2})?\s+(?P<zone>UTC|CET|CEST)\b",
    flags=re.IGNORECASE,
)
SLICES_TIMEZONE_OFFSETS = {"UTC": 0, "CET": 1, "CEST": 2}


@dataclass(frozen=True)
class ProbeResult:
    returncode: int
    stdout: str
    stderr: str = ""


Runner = Callable[[Sequence[str], int], ProbeResult]


def _probe_label(command: Sequence[str]) -> str:
    if not command:
        return "provider access"
    executable = Path(str(command[0])).name
    if executable == "slices":
        action = " ".join(str(part) for part in command[1:3]).strip()
        return f"SLICES {action}" if action else "SLICES"
    if executable == "ssh":
        return "R2Lab SSH gateway"
    return executable


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
        raise WorkspaceError(
            f"{_probe_label(command)} probe timed out after {timeout_seconds}s"
        ) from exc
    return ProbeResult(completed.returncode, completed.stdout or "", completed.stderr or "")


def _parse_slices_expiry(output: str) -> datetime | None:
    match = SLICES_EXPIRY_RE.search(output)
    if match is None:
        return None
    source_zone = timezone(
        timedelta(hours=SLICES_TIMEZONE_OFFSETS[match.group("zone").upper()])
    )
    parsed = datetime.strptime(
        f"{match.group('date')} {match.group('time')}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=source_zone)
    return parsed.astimezone(timezone.utc)


def _refresh_boundary(now: datetime, access_until: datetime | None) -> datetime:
    refresh = now + DEFAULT_ACCESS_REFRESH
    if access_until is not None and refresh > access_until:
        refresh = access_until
    return refresh


def _matching_fresh_record(
    *,
    workspace_root: Path,
    provider: str,
    subject: str,
    scope: str,
    now: datetime,
    identity_fingerprint: str | None = None,
) -> AccessRecord | None:
    record = load_access_record(workspace_root, provider)
    if record is None:
        return None
    if record.subject != subject or record.scope != scope:
        return None
    if identity_fingerprint is not None and record.identity_fingerprint != identity_fingerprint:
        return None
    return record if record.is_fresh(now) else None


def probe_slices_project_access(
    *,
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
    return AccessRecord(
        provider="slices",
        subject=username,
        scope=project,
        verified_at_utc=format_utc(current),
        refresh_after_utc=format_utc(_refresh_boundary(current, access_until)),
        access_until_utc=(format_utc(access_until) if access_until is not None else None),
        detail="authenticated project membership verified",
    )


def verify_slices_project_access(
    *,
    workspace_root: Path,
    username: str,
    project: str,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = 30,
    now: datetime | None = None,
) -> AccessRecord:
    """Verify SLICES project access and persist the resulting read-only evidence."""

    record = probe_slices_project_access(
        username=username,
        project=project,
        runner=runner,
        timeout_seconds=timeout_seconds,
        now=now,
    )
    save_access_record(workspace_root, record)
    return record


def ensure_slices_project_access(
    *,
    workspace_root: Path,
    username: str,
    project: str,
    force: bool = False,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = 30,
    now: datetime | None = None,
) -> tuple[AccessRecord, bool]:
    """Return matching fresh access evidence, or refresh it read-only when needed."""

    current = (now or utc_now()).astimezone(timezone.utc)
    if not force:
        cached = _matching_fresh_record(
            workspace_root=workspace_root,
            provider="slices",
            subject=username,
            scope=project,
            now=current,
        )
        if cached is not None:
            return cached, False
    return (
        verify_slices_project_access(
            workspace_root=workspace_root,
            username=username,
            project=project,
            runner=runner,
            timeout_seconds=timeout_seconds,
            now=current,
        ),
        True,
    )


def _safe_ssh_failure(stderr: str) -> str | None:
    lower = stderr.lower()
    if "permission denied" in lower:
        return "permission denied"
    if "host key verification failed" in lower:
        return "host key verification failed"
    if "could not resolve hostname" in lower or "name or service not known" in lower:
        return "hostname could not be resolved"
    if "connection timed out" in lower or "operation timed out" in lower:
        return "connection timed out"
    if "connection refused" in lower:
        return "connection refused"
    if "no route to host" in lower or "network is unreachable" in lower:
        return "gateway is unreachable"
    return None


def probe_r2lab_gateway_access(
    *,
    slice_name: str,
    identity_reference: str,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = 30,
    now: datetime | None = None,
) -> AccessRecord:
    """Verify strict public-key authentication to Faraday without checking a lease."""

    current = (now or utc_now()).astimezone(timezone.utc)
    identity = resolve_identity_reference(identity_reference)
    fingerprint = ssh_identity_fingerprint(identity)
    command = (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ConnectionAttempts=1",
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
        reason = _safe_ssh_failure(result.stderr)
        suffix = f": {reason}" if reason is not None else ""
        raise WorkspaceError(
            f"R2Lab Faraday public-key access could not be verified{suffix}"
        )
    return AccessRecord(
        provider="r2lab",
        subject=slice_name,
        scope="faraday.inria.fr",
        verified_at_utc=format_utc(current),
        refresh_after_utc=format_utc(current + DEFAULT_ACCESS_REFRESH),
        identity_fingerprint=fingerprint,
        detail="strict public-key gateway access verified",
    )


def verify_r2lab_gateway_access(
    *,
    workspace_root: Path,
    slice_name: str,
    identity_reference: str,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = 30,
    now: datetime | None = None,
) -> AccessRecord:
    """Verify R2Lab gateway access and persist the resulting read-only evidence."""

    record = probe_r2lab_gateway_access(
        slice_name=slice_name,
        identity_reference=identity_reference,
        runner=runner,
        timeout_seconds=timeout_seconds,
        now=now,
    )
    save_access_record(workspace_root, record)
    return record


def ensure_r2lab_gateway_access(
    *,
    workspace_root: Path,
    slice_name: str,
    identity_reference: str,
    force: bool = False,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = 30,
    now: datetime | None = None,
) -> tuple[AccessRecord, bool]:
    """Return matching fresh gateway evidence, or refresh it read-only when needed."""

    current = (now or utc_now()).astimezone(timezone.utc)
    identity = resolve_identity_reference(identity_reference)
    fingerprint = ssh_identity_fingerprint(identity)
    if not force:
        cached = _matching_fresh_record(
            workspace_root=workspace_root,
            provider="r2lab",
            subject=slice_name,
            scope="faraday.inria.fr",
            now=current,
            identity_fingerprint=fingerprint,
        )
        if cached is not None:
            return cached, False
    return (
        verify_r2lab_gateway_access(
            workspace_root=workspace_root,
            slice_name=slice_name,
            identity_reference=identity_reference,
            runner=runner,
            timeout_seconds=timeout_seconds,
            now=current,
        ),
        True,
    )
