"""Persisted experiment observations kept separate from requested configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from synthran.workspace.model import (
    EXPERIMENT_STATUS_SCHEMA,
    ExperimentStatus,
    WorkspaceError,
)
from synthran.workspace.store import experiment_directory


def save_experiment_status(root: Path, status: ExperimentStatus) -> Path:
    directory = experiment_directory(root, status.experiment_id)
    if not (directory / "experiment.toml").is_file():
        raise WorkspaceError(
            f"experiment {status.experiment_id} has no durable experiment record"
        )
    path = directory / "status.json"
    content = json.dumps(status.to_dict(), indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=directory,
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    os.chmod(temporary_path, 0o600)
    temporary_path.replace(path)
    return path


def load_experiment_status(root: Path, experiment_id: str) -> ExperimentStatus:
    path = experiment_directory(root, experiment_id) / "status.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceError(f"experiment {experiment_id} has no persisted status") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"experiment {experiment_id} status is not readable JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != EXPERIMENT_STATUS_SCHEMA:
        raise WorkspaceError(f"experiment {experiment_id} status schema is unsupported")
    notes = value.get("notes", [])
    if not isinstance(notes, list) or any(not isinstance(item, str) for item in notes):
        raise WorkspaceError(f"experiment {experiment_id} status notes are malformed")
    provider_checked = value.get("provider_checked_at_utc")
    if provider_checked is not None and not isinstance(provider_checked, str):
        raise WorkspaceError(
            f"experiment {experiment_id} provider observation time is malformed"
        )
    return ExperimentStatus(
        schema=str(value.get("schema", "")),
        experiment_id=str(value.get("experiment_id", "")),
        state=str(value.get("state", "")),
        updated_at_utc=str(value.get("updated_at_utc", "")),
        provider_checked_at_utc=provider_checked,
        provider_state=str(value.get("provider_state", "unknown")),
        notes=tuple(notes),
    )
