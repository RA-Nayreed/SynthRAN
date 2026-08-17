"""Durable run and operation identity records used to rebuild the workspace index."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from synthran.workspace.model import (
    OPERATION_RECORD_SCHEMA,
    RUN_RECORD_SCHEMA,
    OperationRecord,
    RunRecord,
    WorkspaceError,
)
from synthran.workspace.store import experiment_directory, workspace_directory


def _atomic_json(path: Path, value: dict[str, object]) -> Path:
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


def run_directory(root: Path, experiment_id: str, run_id: str) -> Path:
    return experiment_directory(root, experiment_id) / "runs" / run_id


def operation_directory(root: Path, operation_id: str) -> Path:
    return workspace_directory(root) / "operations" / operation_id


def save_run_record(root: Path, record: RunRecord) -> Path:
    directory = run_directory(root, record.experiment_id, record.run_id)
    if not directory.is_dir():
        raise WorkspaceError(f"run directory does not exist for {record.run_id}")
    return _atomic_json(directory / "run.json", record.to_dict())


def load_run_record(root: Path, experiment_id: str, run_id: str) -> RunRecord:
    path = run_directory(root, experiment_id, run_id) / "run.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceError(f"run {run_id} has no durable record") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"run {run_id} record is not readable JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != RUN_RECORD_SCHEMA:
        raise WorkspaceError(f"run {run_id} record schema is unsupported")
    record = RunRecord.from_dict(value)
    if record.experiment_id != experiment_id or record.run_id != run_id:
        raise WorkspaceError(f"run {run_id} record does not match its directory")
    return record


def save_operation_record(root: Path, record: OperationRecord) -> Path:
    directory = operation_directory(root, record.operation_id)
    if not directory.is_dir():
        raise WorkspaceError(
            f"operation directory does not exist for {record.operation_id}"
        )
    return _atomic_json(directory / "operation.json", record.to_dict())


def load_operation_record(root: Path, operation_id: str) -> OperationRecord:
    path = operation_directory(root, operation_id) / "operation.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceError(f"operation {operation_id} has no durable record") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"operation {operation_id} record is not readable JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != OPERATION_RECORD_SCHEMA:
        raise WorkspaceError(f"operation {operation_id} record schema is unsupported")
    record = OperationRecord.from_dict(value)
    if record.operation_id != operation_id:
        raise WorkspaceError(
            f"operation {operation_id} record does not match its directory"
        )
    return record
