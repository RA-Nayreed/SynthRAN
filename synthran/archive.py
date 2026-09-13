"""Immutable S3 archival for validated SynthRAN experiment evidence.

The scientific result and its archival state are deliberately separate. A
validated local result is never rerun merely because object storage is
unavailable: retrying the same experiment phase validates the existing result
and retries only this archival step.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable


ARCHIVE_FILES = {"archive-manifest.json", "archive-status.json", "_ARCHIVED.json"}


class ArchiveError(RuntimeError):
    """Object-store archival failed after scientific evidence was retained."""


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_canonical(value))
    temporary.replace(path)


def _mc_binary() -> str:
    value = shutil.which("mc")
    if value:
        return value
    fallback = Path.home() / ".local/bin/mc"
    if fallback.is_file() and fallback.stat().st_mode & 0o111:
        return str(fallback)
    raise ArchiveError(
        "MinIO client 'mc' is required for experiment archival. Configure the "
        "declared S3 alias, then rerun the same experiment phase; validated "
        "scientific results will be reused rather than regenerated."
    )


def _run(command: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _remote_sha256(mc: str, remote: str) -> str | None:
    process = subprocess.Popen(
        [mc, "cat", remote],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    digest = hashlib.sha256()
    for block in iter(lambda: process.stdout.read(1024 * 1024), b""):
        digest.update(block)
    stderr = process.stderr.read() if process.stderr is not None else b""
    returncode = process.wait()
    if returncode != 0:
        text = stderr.decode("utf-8", errors="replace").lower()
        if any(token in text for token in ("not found", "does not exist", "nosuchkey")):
            return None
        raise ArchiveError(
            f"mc cat failed for {remote}: {stderr.decode('utf-8', errors='replace').strip()}"
        )
    return digest.hexdigest()


def _put_immutable(mc: str, local: Path, remote: str, expected_sha256: str) -> None:
    existing = _remote_sha256(mc, remote)
    if existing is not None:
        if existing != expected_sha256:
            raise ArchiveError(
                f"refusing to overwrite remote evidence with different content: {remote}"
            )
        return
    result = _run([mc, "cp", str(local), remote])
    if result.returncode != 0:
        raise ArchiveError(
            f"mc cp failed for {remote}: {result.stderr.decode('utf-8', errors='replace').strip()}"
        )
    observed = _remote_sha256(mc, remote)
    if observed != expected_sha256:
        raise ArchiveError(f"remote SHA-256 verification failed for {remote}")


def _safe_files(root: Path, selected: Iterable[Path] | None = None) -> list[Path]:
    root = root.resolve()
    candidates = list(selected) if selected is not None else sorted(root.rglob("*"))
    files = []
    for path in candidates:
        path = Path(path)
        if not path.is_absolute():
            path = root / path
        if path.is_symlink():
            raise ArchiveError(f"refusing to archive symlink: {path}")
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ArchiveError(f"archive path escapes evidence root: {path}")
        if path.name in ARCHIVE_FILES or path.name.startswith("_ARCHIVED."):
            continue
        files.append(resolved)
    return sorted(set(files))


def _destination(settings: dict[str, Any], campaign_id: str, suffix: str) -> str:
    alias = str(settings.get("alias", "")).strip("/")
    bucket = str(settings.get("bucket", "")).strip("/")
    prefix = str(settings.get("prefix", "")).strip("/")
    if not alias or not bucket or not prefix:
        raise ArchiveError("archive alias, bucket and prefix must be configured")
    suffix = suffix.strip("/")
    return f"{alias}/{bucket}/{prefix}/{campaign_id}/{suffix}"


def _status(path: Path, *, state: str, destination: str, error: str | None = None) -> None:
    value = {
        "schema_version": 1,
        "archive_status": state,
        "destination": destination,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if error:
        value["error"] = error
    _write_json(path, value)


def archive_directory(
    evidence_root: str | Path,
    *,
    settings: dict[str, Any],
    experiment: str,
    campaign_id: str,
    archive_kind: str,
    archive_id: str,
    phase: str,
    source_revision: str,
    remote_suffix: str,
    selected_files: Iterable[str | Path] | None = None,
) -> dict[str, Any]:
    """Archive one immutable evidence unit and verify every remote byte stream."""

    root = Path(evidence_root).resolve()
    if not root.is_dir():
        raise ArchiveError(f"archive evidence root is missing: {root}")
    if not bool(settings.get("enabled", False)):
        return {"archive_status": "disabled"}
    if settings.get("backend") != "s3":
        raise ArchiveError(f"unsupported archive backend: {settings.get('backend')}")
    if not bool(settings.get("remote_verify", True)):
        raise ArchiveError("experiment archival requires remote verification")

    destination = _destination(settings, campaign_id, remote_suffix)
    status_path = root / "archive-status.json"
    try:
        selected = (
            [root / Path(path) for path in selected_files]
            if selected_files is not None
            else None
        )
        files = _safe_files(root, selected)
        manifest = {
            "schema_version": 1,
            "experiment": experiment,
            "campaign_id": campaign_id,
            "archive_kind": archive_kind,
            "archive_id": archive_id,
            "phase": phase,
            "scientific_status": "SUCCESS",
            "source_revision": source_revision,
            "destination": destination,
            "replay_evidence": "included_if_present",
            "files": {
                str(path.relative_to(root)): {
                    "sha256": _sha256(path),
                    "bytes": path.stat().st_size,
                }
                for path in files
            },
        }
        manifest_bytes = _canonical(manifest)
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_path = root / "archive-manifest.json"
        manifest_path.write_bytes(manifest_bytes)

        mc = _mc_binary()
        for path in files:
            relative = path.relative_to(root).as_posix()
            _put_immutable(
                mc,
                path,
                f"{destination}/{relative}",
                manifest["files"][relative]["sha256"],
            )
        _put_immutable(
            mc,
            manifest_path,
            f"{destination}/archive-manifest.json",
            manifest_sha256,
        )

        marker = {
            "schema_version": 1,
            "archive_status": "VERIFIED",
            "archived_at_utc": datetime.now(timezone.utc).isoformat(),
            "destination": destination,
            "manifest_sha256": manifest_sha256,
        }
        marker_path = root / "_ARCHIVED.json"
        marker_path.write_bytes(_canonical(marker))
        _put_immutable(
            mc,
            marker_path,
            f"{destination}/_ARCHIVED.json",
            _sha256(marker_path),
        )
        _status(status_path, state="VERIFIED", destination=destination)
        return {**marker, "files_verified": len(files)}
    except Exception as exc:
        message = str(exc)
        _status(status_path, state="FAILED", destination=destination, error=message)
        if isinstance(exc, ArchiveError):
            raise
        raise ArchiveError(message) from exc


def archive_run(
    run_root: str | Path,
    *,
    settings: dict[str, Any],
    campaign: dict[str, Any],
    phase: str,
    run_id: str,
) -> dict[str, Any]:
    return archive_directory(
        run_root,
        settings=settings,
        experiment=str(campaign["experiment"]),
        campaign_id=str(campaign["campaign_id"]),
        archive_kind="run",
        archive_id=run_id,
        phase=phase,
        source_revision=str(campaign["source_revision"]),
        remote_suffix=f"runs/{run_id}",
    )


def archive_campaign_snapshot(
    campaign_root: str | Path,
    *,
    settings: dict[str, Any],
    phase: str,
    selected_files: Iterable[str | Path],
) -> dict[str, Any]:
    root = Path(campaign_root).resolve()
    campaign = json.loads((root / "campaign.json").read_text(encoding="utf-8"))
    snapshot_root = root / "archive-snapshots" / phase
    if snapshot_root.exists() and (snapshot_root / "_ARCHIVED.json").is_file():
        return json.loads((snapshot_root / "_ARCHIVED.json").read_text(encoding="utf-8"))
    snapshot_root.mkdir(parents=True, exist_ok=True)
    for relative in selected_files:
        source = root / Path(relative)
        if not source.is_file():
            raise ArchiveError(f"campaign artifact is missing: {source}")
        target = snapshot_root / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if _sha256(target) != _sha256(source):
                raise ArchiveError(f"campaign snapshot changed: {relative}")
        else:
            shutil.copyfile(source, target)
    return archive_directory(
        snapshot_root,
        settings=settings,
        experiment=str(campaign["experiment"]),
        campaign_id=str(campaign["campaign_id"]),
        archive_kind="campaign-snapshot",
        archive_id=phase,
        phase=phase,
        source_revision=str(campaign["source_revision"]),
        remote_suffix=f"snapshots/{phase}",
    )
