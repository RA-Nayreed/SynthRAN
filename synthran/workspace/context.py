"""Resolve durable workspace authority for terminal and command interfaces."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from synthran.workspace.model import ExperimentRecord, Profile, WorkspaceConfig, WorkspaceError
from synthran.workspace.store import (
    find_workspace_root,
    load_active_experiment_id,
    load_experiment_record,
    load_profile,
    load_workspace,
    resolve_identity_reference,
    verify_profile_identity,
)


@dataclass(frozen=True)
class WorkspaceAuthorityContext:
    """Locally durable authority selections before live provider reconciliation."""

    root: Path
    workspace: WorkspaceConfig
    profile: Profile
    active_experiment: ExperimentRecord | None
    slices_project: str
    slices_experiment: str | None
    r2lab_slice: str | None
    r2lab_identity: Path | None
    r2lab_identity_fingerprint: str | None

    @property
    def experiment_id(self) -> str | None:
        return (
            self.active_experiment.experiment_id
            if self.active_experiment is not None
            else None
        )


def _declared_value(
    *,
    explicit: str | None,
    environment: Mapping[str, str],
    environment_name: str,
) -> str | None:
    return explicit if explicit is not None else environment.get(environment_name)


def _require_match(
    *,
    label: str,
    durable: str | None,
    declared: str | None,
) -> None:
    if declared is None:
        return
    if durable is None:
        raise WorkspaceError(
            f"{label} was supplied but the initialized workspace has no durable binding"
        )
    if declared != durable:
        raise WorkspaceError(
            f"{label} conflicts with the initialized workspace source of truth"
        )


def resolve_workspace_authority(
    *,
    start: Path | None = None,
    environment: Mapping[str, str] | None = None,
    slices_project: str | None = None,
    slices_experiment: str | None = None,
    r2lab_slice: str | None = None,
) -> WorkspaceAuthorityContext:
    """Resolve profile/workspace/experiment bindings and reject conflicting overrides."""

    env = environment if environment is not None else os.environ
    root = find_workspace_root(start, environment=env)
    workspace = load_workspace(root)
    profile = load_profile(workspace.profile, environment=env)
    observed_fingerprint = verify_profile_identity(profile)

    declared_project = _declared_value(
        explicit=slices_project,
        environment=env,
        environment_name="SYNTHRAN_SLICES_PROJECT",
    )
    _require_match(
        label="SLICES project",
        durable=workspace.project,
        declared=declared_project,
    )

    active_experiment: ExperimentRecord | None = None
    provider_experiment: str | None = None
    active_id = load_active_experiment_id(root)
    if active_id is not None:
        active_experiment = load_experiment_record(root, active_id)
        if active_experiment.profile != workspace.profile:
            raise WorkspaceError("active experiment profile does not match the workspace")
        if active_experiment.project != workspace.project:
            raise WorkspaceError("active experiment project does not match the workspace")
        provider_experiment = active_experiment.slices_experiment

    declared_experiment = _declared_value(
        explicit=slices_experiment,
        environment=env,
        environment_name="SYNTHRAN_SLICES_EXPERIMENT",
    )
    _require_match(
        label="SLICES experiment",
        durable=provider_experiment,
        declared=declared_experiment,
    )

    if (profile.r2lab_slice is None) != (profile.r2lab_identity is None):
        raise WorkspaceError("selected profile has incomplete R2Lab authority data")
    declared_r2lab_slice = _declared_value(
        explicit=r2lab_slice,
        environment=env,
        environment_name="SYNTHRAN_R2LAB_SLICE",
    )
    _require_match(
        label="R2Lab slice",
        durable=profile.r2lab_slice,
        declared=declared_r2lab_slice,
    )

    identity: Path | None = None
    if profile.r2lab_identity is not None:
        identity = resolve_identity_reference(profile.r2lab_identity)
        if observed_fingerprint != profile.r2lab_identity_fingerprint:
            raise WorkspaceError("R2Lab identity fingerprint does not match the profile")

    return WorkspaceAuthorityContext(
        root=root,
        workspace=workspace,
        profile=profile,
        active_experiment=active_experiment,
        slices_project=workspace.project,
        slices_experiment=provider_experiment,
        r2lab_slice=profile.r2lab_slice,
        r2lab_identity=identity,
        r2lab_identity_fingerprint=profile.r2lab_identity_fingerprint,
    )
