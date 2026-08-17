"""Durable operation plans, approval evidence, state, events, and mutation claim."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from synthran.operations.model import (
    APPROVAL_SCHEMA,
    OPERATION_PLAN_SCHEMA,
    OPERATION_STATE_SCHEMA,
    ApprovalGrant,
    OperationEvent,
    OperationPlan,
    OperationState,
)
from synthran.workspace.model import WorkspaceError, validate_operation_id
from synthran.workspace.records import operation_directory
from synthran.workspace.store import workspace_directory


ACTIVE_MUTATION_SCHEMA = "synthran/active-mutation/v1alpha1"


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def digest_json(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    os.chmod(temporary_path, 0o600)
    temporary_path.replace(path)
    return path


def _load_object(path: Path, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceError(f"{label} was not found") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise WorkspaceError(f"{label} must contain one JSON object")
    return value


def plan_path(root: Path, operation_id: str) -> Path:
    validate_operation_id(operation_id)
    return operation_directory(root, operation_id) / "plan.json"


def state_path(root: Path, operation_id: str) -> Path:
    validate_operation_id(operation_id)
    return operation_directory(root, operation_id) / "state.json"


def approval_path(root: Path, operation_id: str) -> Path:
    validate_operation_id(operation_id)
    return operation_directory(root, operation_id) / "approval.json"


def operation_events_path(root: Path, operation_id: str) -> Path:
    validate_operation_id(operation_id)
    return operation_directory(root, operation_id) / "events.jsonl"


def session_events_path(root: Path) -> Path:
    return workspace_directory(root) / "sessions" / "events.jsonl"


def active_mutation_path(root: Path) -> Path:
    return workspace_directory(root) / "operations" / "active-mutation.json"


def save_plan(root: Path, plan: OperationPlan) -> Path:
    directory = operation_directory(root, plan.operation_id)
    if not directory.is_dir():
        raise WorkspaceError(f"operation directory does not exist for {plan.operation_id}")
    expected = digest_json(plan.unsigned_dict())
    if expected != plan.plan_sha256:
        raise WorkspaceError("operation plan digest does not match its content")
    path = plan_path(root, plan.operation_id)
    if path.exists():
        raise WorkspaceError("operation plan already exists and is immutable")
    return _atomic_json(path, plan.to_dict())


def load_plan(root: Path, operation_id: str) -> OperationPlan:
    value = _load_object(plan_path(root, operation_id), "operation plan")
    if value.get("schema") != OPERATION_PLAN_SCHEMA:
        raise WorkspaceError("operation plan schema is unsupported")
    plan = OperationPlan.from_dict(value)
    if plan.operation_id != operation_id:
        raise WorkspaceError("operation plan does not match its directory")
    if digest_json(plan.unsigned_dict()) != plan.plan_sha256:
        raise WorkspaceError("operation plan integrity check failed")
    return plan


def save_state(root: Path, state: OperationState) -> Path:
    return _atomic_json(state_path(root, state.operation_id), state.to_dict())


def load_state(root: Path, operation_id: str) -> OperationState:
    value = _load_object(state_path(root, operation_id), "operation state")
    if value.get("schema") != OPERATION_STATE_SCHEMA:
        raise WorkspaceError("operation state schema is unsupported")
    state = OperationState.from_dict(value)
    if state.operation_id != operation_id:
        raise WorkspaceError("operation state does not match its directory")
    return state


def save_approval(root: Path, approval: ApprovalGrant) -> Path:
    plan = load_plan(root, approval.operation_id)
    if approval.plan_sha256 != plan.plan_sha256 or approval.risk != plan.risk:
        raise WorkspaceError("approval does not match the immutable operation plan")
    path = approval_path(root, approval.operation_id)
    if path.exists():
        raise WorkspaceError("operation approval already exists and is immutable")
    return _atomic_json(path, approval.to_dict())


def load_approval(root: Path, operation_id: str) -> ApprovalGrant | None:
    path = approval_path(root, operation_id)
    if not path.exists():
        return None
    value = _load_object(path, "operation approval")
    if value.get("schema") != APPROVAL_SCHEMA:
        raise WorkspaceError("operation approval schema is unsupported")
    approval = ApprovalGrant.from_dict(value)
    plan = load_plan(root, operation_id)
    if approval.operation_id != operation_id:
        raise WorkspaceError("operation approval does not match its directory")
    if approval.plan_sha256 != plan.plan_sha256 or approval.risk != plan.risk:
        raise WorkspaceError("operation approval does not match the immutable plan")
    return approval


def _load_event_objects(path: Path) -> list[Mapping[str, object]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise WorkspaceError("operation event log is not readable") from exc
    result: list[Mapping[str, object]] = []
    for line in lines:
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkspaceError("operation event log contains malformed JSON") from exc
        if not isinstance(value, dict):
            raise WorkspaceError("operation event log entry must be one JSON object")
        result.append(value)
    return result


def next_event_sequence(root: Path, operation_id: str) -> int:
    entries = _load_event_objects(operation_events_path(root, operation_id))
    expected = 1
    for value in entries:
        if value.get("operation_id") != operation_id or value.get("sequence") != expected:
            raise WorkspaceError("operation event sequence is not contiguous")
        expected += 1
    return expected


def append_event(root: Path, event: OperationEvent) -> None:
    expected = next_event_sequence(root, event.operation_id)
    if event.sequence != expected:
        raise WorkspaceError("operation event sequence does not match the journal")
    encoded = (json.dumps(event.to_dict(), sort_keys=True) + "\n").encode("utf-8")
    for path in (
        operation_events_path(root, event.operation_id),
        session_events_path(root),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            written = os.write(descriptor, encoded)
            if written != len(encoded):
                raise WorkspaceError("operation event could not be appended atomically")
        finally:
            os.close(descriptor)


def _load_active_mutation(root: Path) -> Mapping[str, object] | None:
    path = active_mutation_path(root)
    if not path.exists():
        return None
    value = _load_object(path, "active mutation claim")
    if value.get("schema") != ACTIVE_MUTATION_SCHEMA:
        raise WorkspaceError("active mutation claim schema is unsupported")
    return value


def acquire_mutation_claim(root: Path, plan: OperationPlan, created_at_utc: str) -> Path:
    if not plan.mutates:
        raise WorkspaceError("read-only operation cannot acquire a mutation claim")
    path = active_mutation_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": ACTIVE_MUTATION_SCHEMA,
        "operation_id": plan.operation_id,
        "plan_sha256": plan.plan_sha256,
        "created_at_utc": created_at_utc,
    }
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        active = _load_active_mutation(root)
        active_id = active.get("operation_id") if active is not None else "unknown"
        raise WorkspaceError(
            f"another mutating operation is active ({active_id}); reconcile it first"
        ) from exc
    try:
        written = os.write(descriptor, encoded)
        if written != len(encoded):
            path.unlink(missing_ok=True)
            raise WorkspaceError("active mutation claim could not be written atomically")
    finally:
        os.close(descriptor)
    return path


def require_mutation_claim(root: Path, plan: OperationPlan) -> None:
    value = _load_active_mutation(root)
    if value is None:
        raise WorkspaceError("active mutation claim is missing")
    if (
        value.get("operation_id") != plan.operation_id
        or value.get("plan_sha256") != plan.plan_sha256
    ):
        raise WorkspaceError("active mutation claim belongs to another operation")


def release_mutation_claim(root: Path, plan: OperationPlan) -> None:
    require_mutation_claim(root, plan)
    active_mutation_path(root).unlink()
