"""High-level experiment persistence services shared by terminal and scripted interfaces."""

from __future__ import annotations

from datetime import datetime, timezone

from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.desired_store import save_desired_state
from synthran.workspace.model import ExperimentRecord, ExperimentStatus, WorkspaceError, format_utc, utc_now
from synthran.workspace.registry import WorkspaceRegistry
from synthran.workspace.status import save_experiment_status
from synthran.workspace.store import set_active_experiment


def create_desired_experiment(
    registry: WorkspaceRegistry,
    *,
    profile: str,
    project: str,
    desired: ExperimentDesiredState,
    label: str | None = None,
    slices_experiment: str | None = None,
    activate: bool = True,
    now: datetime | None = None,
) -> ExperimentRecord:
    """Issue one non-reusable experiment ID and persist its complete requested state."""

    current = (now or utc_now()).astimezone(timezone.utc)
    record = registry.create_experiment(
        profile=profile,
        project=project,
        label=label,
        slices_experiment=slices_experiment,
        network_intent=desired.intent,
        radio_mode=desired.radio.mode,
        now=current,
        activate=False,
    )
    try:
        save_desired_state(
            registry.workspace_root,
            record.experiment_id,
            desired,
        )
        if activate:
            set_active_experiment(registry.workspace_root, record.experiment_id)
    except Exception as exc:
        registry.mark_experiment_status(record.experiment_id, "failed")
        try:
            save_experiment_status(
                registry.workspace_root,
                ExperimentStatus(
                    experiment_id=record.experiment_id,
                    state="failed",
                    updated_at_utc=format_utc(utc_now()),
                    notes=("detailed desired-state persistence did not complete",),
                ),
            )
        except Exception:
            pass
        if isinstance(exc, WorkspaceError):
            raise
        raise WorkspaceError(
            f"experiment {record.experiment_id} desired state could not be persisted; ID remains consumed"
        ) from exc
    return record
