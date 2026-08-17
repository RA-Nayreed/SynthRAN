"""Resolve one SynthRAN workspace session without granting stale mutation authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Mapping

from synthran.workspace.access import (
    AccessRecord,
    Runner,
    ensure_r2lab_gateway_access,
    ensure_slices_project_access,
    subprocess_runner,
)
from synthran.workspace.context import resolve_workspace_authority
from synthran.workspace.model import (
    ExperimentRecord,
    ExperimentStatus,
    Profile,
    WorkspaceConfig,
    WorkspaceError,
    format_utc,
    utc_now,
    validate_safe_name,
)
from synthran.workspace.status import save_experiment_status


CONTEXT_ALPHABET = r"A-Za-z0-9._:-"


@dataclass(frozen=True)
class AccessState:
    record: AccessRecord
    refreshed: bool


@dataclass(frozen=True)
class ProviderExperimentObservation:
    experiment: str
    state: str
    checked_at_utc: str
    detail: str

    @property
    def usable(self) -> bool:
        return self.state == "active"


@dataclass(frozen=True)
class WorkspaceSession:
    root: Path
    workspace: WorkspaceConfig
    profile: Profile
    slices_access: AccessState
    r2lab_access: AccessState | None
    active_experiment: ExperimentRecord | None
    provider_experiment: ProviderExperimentObservation | None

    @property
    def experiment_id(self) -> str | None:
        return (
            self.active_experiment.experiment_id
            if self.active_experiment is not None
            else None
        )


def _contains_exact_context(output: str, expected: str) -> bool:
    pattern = re.compile(
        rf"(?<![{CONTEXT_ALPHABET}]){re.escape(expected)}(?![{CONTEXT_ALPHABET}])"
    )
    return pattern.search(output) is not None


def verify_slices_experiment_binding(
    *,
    experiment: str,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = 30,
    now: datetime | None = None,
) -> ProviderExperimentObservation:
    """Check a temporary provider experiment every time its binding is resumed."""

    validate_safe_name(experiment, "SLICES experiment")
    current = (now or utc_now()).astimezone(timezone.utc)
    result = runner(("slices", "experiment", "show", experiment), timeout_seconds)
    output = "\n".join((result.stdout, result.stderr)).strip()
    lower = output.lower()
    if result.returncode == 0:
        if not _contains_exact_context(output, experiment):
            raise WorkspaceError(
                "SLICES experiment probe succeeded but did not identify the bound experiment"
            )
        return ProviderExperimentObservation(
            experiment=experiment,
            state="active",
            checked_at_utc=format_utc(current),
            detail="provider experiment verified",
        )
    if "expired" in lower:
        state = "expired"
        detail = "provider reports the experiment as expired"
    elif "not found" in lower or "404" in lower or "does not exist" in lower:
        state = "missing"
        detail = "provider experiment is no longer present"
    else:
        state = "unreachable"
        detail = "provider experiment could not be verified"
    return ProviderExperimentObservation(
        experiment=experiment,
        state=state,
        checked_at_utc=format_utc(current),
        detail=detail,
    )


def _persist_provider_observation(
    *,
    root: Path,
    record: ExperimentRecord,
    observation: ProviderExperimentObservation,
    now: datetime,
) -> None:
    if observation.state == "active":
        state = "active"
    elif observation.state == "expired":
        state = "expired"
    else:
        state = "configured"
    save_experiment_status(
        root,
        ExperimentStatus(
            experiment_id=record.experiment_id,
            state=state,
            updated_at_utc=format_utc(now),
            provider_checked_at_utc=observation.checked_at_utc,
            provider_state=observation.state,
            notes=(observation.detail,),
        ),
    )


def open_workspace_session(
    *,
    start: Path | None = None,
    environment: Mapping[str, str] | None = None,
    force_access_refresh: bool = False,
    timeout_seconds: int = 30,
    slices_runner: Runner = subprocess_runner,
    r2lab_runner: Runner = subprocess_runner,
    experiment_runner: Runner = subprocess_runner,
    now: datetime | None = None,
) -> WorkspaceSession:
    """Load durable authority, reuse fresh access evidence, and recheck temporary experiment state."""

    current = (now or utc_now()).astimezone(timezone.utc)
    authority = resolve_workspace_authority(start=start, environment=environment)
    root = authority.root
    workspace = authority.workspace
    profile = authority.profile
    if profile.slices_username is None:
        raise WorkspaceError("selected profile has no SLICES username")

    slices_record, slices_refreshed = ensure_slices_project_access(
        workspace_root=root,
        username=profile.slices_username,
        project=authority.slices_project,
        force=force_access_refresh,
        runner=slices_runner,
        timeout_seconds=timeout_seconds,
        now=current,
    )
    slices_access = AccessState(slices_record, slices_refreshed)

    r2lab_access: AccessState | None = None
    if authority.r2lab_slice is not None and authority.r2lab_identity is not None:
        r2lab_record, r2lab_refreshed = ensure_r2lab_gateway_access(
            workspace_root=root,
            slice_name=authority.r2lab_slice,
            identity_reference=str(authority.r2lab_identity),
            force=force_access_refresh,
            runner=r2lab_runner,
            timeout_seconds=timeout_seconds,
            now=current,
        )
        r2lab_access = AccessState(r2lab_record, r2lab_refreshed)

    active_experiment = authority.active_experiment
    provider_experiment: ProviderExperimentObservation | None = None
    if active_experiment is not None and authority.slices_experiment is not None:
        provider_experiment = verify_slices_experiment_binding(
            experiment=authority.slices_experiment,
            runner=experiment_runner,
            timeout_seconds=timeout_seconds,
            now=current,
        )
        _persist_provider_observation(
            root=root,
            record=active_experiment,
            observation=provider_experiment,
            now=current,
        )

    return WorkspaceSession(
        root=root,
        workspace=workspace,
        profile=profile,
        slices_access=slices_access,
        r2lab_access=r2lab_access,
        active_experiment=active_experiment,
        provider_experiment=provider_experiment,
    )
