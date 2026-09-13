"""Read-only discovery of the currently accepted SynthRAN testbed.

Experiments consume infrastructure; they do not reserve, repair, rebuild, or
reconfigure it.  This module turns the active deployment endpoint published by
``deploy.sh`` into a concise execution environment and reports current
reservation coverage when it can be proven.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from synthran.testbed_attachment import attach_active_deployment

ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _stamp(value: object) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("reservation timestamp is missing")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return parsed.astimezone(dt.timezone.utc)


def _saved_pos_coverage(result_dir: Path, now: dt.datetime) -> dict[str, Any]:
    path = result_dir / "pos-selection.json"
    if not path.is_file():
        return {"status": "unmanaged", "source": None, "coverage_end": None}
    try:
        value = _read_json(path)
        end = _stamp(value.get("coverage_end"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"status": "unverified", "source": str(path), "coverage_end": None}
    return {
        "status": "active" if end > now else "expired",
        "source": str(path),
        "coverage_end": end.isoformat(),
    }


def _fresh_pos_coverage(deployment: dict[str, Any], result_dir: Path, now: dt.datetime) -> dict[str, Any]:
    """Prove current SOP calendar coverage when the POS CLI is available."""

    if shutil.which("pos") is None:
        return _saved_pos_coverage(result_dir, now)
    process = subprocess.run(
        ["pos", "calendar", "list", "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode:
        saved = _saved_pos_coverage(result_dir, now)
        saved["detail"] = "fresh POS calendar query failed; showing saved deployment coverage"
        return saved
    try:
        events = json.loads(process.stdout)
    except json.JSONDecodeError:
        saved = _saved_pos_coverage(result_dir, now)
        saved["detail"] = "fresh POS calendar output was unreadable; showing saved deployment coverage"
        return saved
    if not isinstance(events, list):
        return {"status": "unverified", "source": "pos calendar list", "coverage_end": None}

    owner = os.environ.get("USER") or subprocess.run(
        ["id", "-un"], text=True, capture_output=True, check=False
    ).stdout.strip()
    nodes = list(dict.fromkeys(str(value) for value in deployment.get("nodes", {}).values()))
    if not nodes:
        return {"status": "unverified", "source": "pos calendar list", "coverage_end": None}

    ends: list[dt.datetime] = []
    missing: list[str] = []
    for node in nodes:
        covering = []
        for event in events:
            if not isinstance(event, dict) or event.get("owner") != owner:
                continue
            if node not in event.get("nodes", []):
                continue
            try:
                start, end = _stamp(event.get("start_date")), _stamp(event.get("end_date"))
            except ValueError:
                continue
            if start <= now < end:
                covering.append(end)
        if not covering:
            missing.append(node)
        else:
            ends.append(max(covering))
    if missing:
        return {
            "status": "missing",
            "source": "pos calendar list",
            "coverage_end": None,
            "missing_nodes": missing,
        }
    end = min(ends)
    return {
        "status": "active" if end > now else "expired",
        "source": "pos calendar list",
        "coverage_end": end.isoformat(),
        "nodes": nodes,
    }


def _r2lab_coverage(result_dir: Path, now: dt.datetime) -> dict[str, Any]:
    """Read the provider-verified lease retained by the accepted deployment."""

    path = result_dir / "r2lab-lease.json"
    if not path.is_file():
        return {"status": "missing", "source": None, "coverage_end": None}
    try:
        value = _read_json(path)
        lease = value.get("provider_lease") or {}
        raw_end = lease.get("end_epoch")
        if raw_end is not None:
            end = dt.datetime.fromtimestamp(float(raw_end), tz=dt.timezone.utc)
        else:
            end = _stamp(lease.get("t_until"))
    except (OSError, ValueError, TypeError):
        return {"status": "unverified", "source": str(path), "coverage_end": None}
    return {
        "status": "active" if end > now else "expired",
        "source": str(path),
        "coverage_end": end.isoformat(),
        "lease_id": lease.get("id"),
        "slice_name": lease.get("slice_name"),
    }


def inspect_active_deployment() -> dict[str, Any]:
    """Return the accepted deployment plus current execution context.

    Deployment identity is cryptographically rechecked by ``attach_active_deployment``.
    Reservation evidence is deliberately separate: extending a reservation must not
    turn an otherwise identical testbed into a different scientific deployment.
    """

    attachment = attach_active_deployment()
    identity = _read_json(attachment["identity_file"])
    evidence = _read_json(attachment["evidence_file"])
    deployment = identity.get("deployment")
    if not isinstance(deployment, dict):
        raise ValueError("active deployment identity has no deployment mapping")
    result_dir = Path(attachment["result_dir"]).resolve()
    now = dt.datetime.now(dt.timezone.utc)

    sop = _fresh_pos_coverage(deployment, result_dir, now)
    r2lab = (
        _r2lab_coverage(result_dir, now)
        if deployment.get("platform") == "r2lab"
        else {"status": "not-required", "source": None, "coverage_end": None}
    )
    ends = []
    for item in (sop, r2lab):
        if item.get("coverage_end"):
            try:
                ends.append(_stamp(item["coverage_end"]))
            except ValueError:
                pass
    coverage_end = min(ends) if ends else None
    remaining = max(0.0, (coverage_end - now).total_seconds()) if coverage_end else None

    bindings = evidence.get("bindings", [])
    if not isinstance(bindings, list):
        bindings = []
    warnings: list[str] = []
    if sop.get("status") != "active":
        warnings.append(f"SOP reservation status is {sop.get('status')}")
    if deployment.get("platform") == "r2lab" and r2lab.get("status") != "active":
        warnings.append(f"R2Lab reservation status is {r2lab.get('status')}")
    if len(bindings) < 2:
        warnings.append("fewer than two verified UE bindings are available")

    return {
        "attachment": attachment,
        "deployment": deployment,
        "evidence": evidence,
        "deployment_hash": attachment["deployment_hash"],
        "result_dir": str(result_dir),
        "bindings": bindings,
        "reservation": {
            "sop": sop,
            "r2lab": r2lab,
            "coverage_end": coverage_end.isoformat() if coverage_end else None,
            "remaining_seconds": remaining,
        },
        "warnings": warnings,
    }


def reservation_remaining_seconds(environment: dict[str, Any]) -> float | None:
    end = environment.get("reservation", {}).get("coverage_end")
    if not end:
        return None
    try:
        return max(0.0, (_stamp(end) - dt.datetime.now(dt.timezone.utc)).total_seconds())
    except ValueError:
        return None
