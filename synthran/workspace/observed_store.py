"""Persist reconciled observed state without promoting it to mutation authority."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from synthran.workspace.model import WorkspaceError
from synthran.workspace.observed import OBSERVED_STATE_SCHEMA, ObservedState
from synthran.workspace.store import experiment_directory


OBSERVED_STATE_FILE = "observed.json"


def observed_state_path(root: Path, experiment_id: str) -> Path:
    return experiment_directory(root, experiment_id) / OBSERVED_STATE_FILE


def save_observed_state(root: Path, state: ObservedState) -> Path:
    directory = experiment_directory(root, state.experiment_id)
    if not (directory / "experiment.toml").is_file():
        raise WorkspaceError(
            f"experiment {state.experiment_id} has no durable experiment record"
        )
    path = directory / OBSERVED_STATE_FILE
    content = json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n"
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


def load_observed_state(root: Path, experiment_id: str) -> ObservedState:
    path = observed_state_path(root, experiment_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceError(
            f"experiment {experiment_id} has no observed-state snapshot"
        ) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceError(
            f"experiment {experiment_id} observed state is not readable JSON"
        ) from exc
    if not isinstance(value, dict) or value.get("schema") != OBSERVED_STATE_SCHEMA:
        raise WorkspaceError("observed-state snapshot schema is unsupported")
    state = ObservedState.from_dict(value)
    if state.experiment_id != experiment_id:
        raise WorkspaceError("observed-state snapshot is in the wrong experiment folder")
    return state
