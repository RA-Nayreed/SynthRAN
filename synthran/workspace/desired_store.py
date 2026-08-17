"""Durable desired-state documents stored inside self-describing experiment folders."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import WorkspaceError
from synthran.workspace.store import experiment_directory, load_experiment_record


DESIRED_STATE_SCHEMA = "synthran/experiment-desired/v1alpha1"
DESIRED_STATE_FILE = "desired.json"


def desired_state_path(root: Path, experiment_id: str) -> Path:
    return experiment_directory(root, experiment_id) / DESIRED_STATE_FILE


def _record_compatible(root: Path, experiment_id: str, desired: ExperimentDesiredState) -> None:
    record = load_experiment_record(root, experiment_id)
    if record.network_intent not in {"unspecified", desired.intent}:
        raise WorkspaceError(
            "experiment desired intent conflicts with the issued experiment record"
        )
    if record.radio_mode not in {"automatic", desired.radio.mode}:
        raise WorkspaceError(
            "experiment desired radio mode conflicts with the issued experiment record"
        )


def save_desired_state(
    root: Path,
    experiment_id: str,
    desired: ExperimentDesiredState,
    *,
    replace: bool = False,
) -> Path:
    """Persist desired configuration without mixing provider observations into it."""

    _record_compatible(root, experiment_id, desired)
    path = desired_state_path(root, experiment_id)
    if path.exists() and not replace:
        raise WorkspaceError(
            f"experiment {experiment_id} already has desired state; replace it explicitly"
        )
    value = {
        "schema": DESIRED_STATE_SCHEMA,
        "experiment_id": experiment_id,
        "desired": desired.to_dict(),
    }
    content = json.dumps(value, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
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


def load_desired_state(root: Path, experiment_id: str) -> ExperimentDesiredState:
    path = desired_state_path(root, experiment_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceError(
            f"experiment {experiment_id} has no detailed desired-state document"
        ) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceError(
            f"experiment {experiment_id} desired state is not readable JSON"
        ) from exc
    if not isinstance(value, dict) or value.get("schema") != DESIRED_STATE_SCHEMA:
        raise WorkspaceError("experiment desired-state schema is unsupported")
    if value.get("experiment_id") != experiment_id:
        raise WorkspaceError("experiment desired-state document is in the wrong folder")
    desired_value = value.get("desired")
    if not isinstance(desired_value, dict):
        raise WorkspaceError("experiment desired-state document is malformed")
    desired = ExperimentDesiredState.from_dict(desired_value)
    _record_compatible(root, experiment_id, desired)
    return desired
