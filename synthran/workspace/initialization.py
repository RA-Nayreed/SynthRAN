"""Verified first-use initialization for one SynthRAN controller workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Mapping

from synthran.workspace.access import (
    AccessRecord,
    Runner,
    probe_r2lab_gateway_access,
    probe_slices_project_access,
    subprocess_runner,
)
from synthran.workspace.model import (
    Profile,
    WorkspaceConfig,
    WorkspaceError,
    format_utc,
    utc_now,
    validate_profile_name,
    validate_safe_name,
)
from synthran.workspace.store import (
    DEFAULT_PROFILE_NAME,
    initialize_workspace,
    load_profile,
    normalize_identity_reference,
    profile_path,
    resolve_identity_reference,
    save_access_record,
    save_profile,
    ssh_identity_fingerprint,
    workspace_directory,
    workspace_file,
)


@dataclass(frozen=True)
class InitializationRequest:
    """Stable identity and workspace choices supplied by the first-use interface."""

    root: Path
    project: str
    profile_name: str = DEFAULT_PROFILE_NAME
    slices_username: str | None = None
    r2lab_slice: str | None = None
    r2lab_identity: Path | None = None
    reservation_minutes: int = 120
    placement: str = "automatic"
    reuse_profile: bool = False

    def __post_init__(self) -> None:
        validate_profile_name(self.profile_name)
        validate_safe_name(self.project, "SLICES project")
        if self.reuse_profile:
            if any(
                value is not None
                for value in (
                    self.slices_username,
                    self.r2lab_slice,
                    self.r2lab_identity,
                )
            ):
                raise WorkspaceError(
                    "profile identity fields cannot be overridden when reusing a profile"
                )
            return
        if self.slices_username is None:
            raise WorkspaceError("SLICES username is required when creating a profile")
        validate_safe_name(self.slices_username, "SLICES username")
        if self.r2lab_slice is not None:
            validate_safe_name(self.r2lab_slice, "R2Lab slice")
        if (self.r2lab_slice is None) != (self.r2lab_identity is None):
            raise WorkspaceError(
                "R2Lab slice and SSH identity must either both be set or both be absent"
            )


@dataclass(frozen=True)
class InitializationResult:
    profile: Profile
    workspace: WorkspaceConfig
    slices_access: AccessRecord
    r2lab_access: AccessRecord | None
    profile_created: bool


@dataclass(frozen=True)
class InitializationPlan:
    """Read-only result ready to be persisted as one local workspace."""

    request: InitializationRequest
    profile: Profile
    slices_access: AccessRecord
    r2lab_access: AccessRecord | None
    profile_created: bool


def _profile_from_request(
    request: InitializationRequest,
    *,
    environment: Mapping[str, str] | None,
    now: datetime,
) -> tuple[Profile, bool]:
    path = profile_path(request.profile_name, environment=environment)
    if request.reuse_profile:
        profile = load_profile(request.profile_name, environment=environment)
        if profile.r2lab_identity is not None:
            observed = ssh_identity_fingerprint(
                resolve_identity_reference(profile.r2lab_identity)
            )
            if observed != profile.r2lab_identity_fingerprint:
                raise WorkspaceError(
                    "existing profile R2Lab identity fingerprint no longer matches"
                )
        return profile, False

    if path.exists():
        raise WorkspaceError(
            f"SynthRAN profile '{request.profile_name}' already exists; reuse it explicitly"
        )
    if request.slices_username is None:
        raise WorkspaceError("SLICES username is required when creating a profile")

    identity_reference: str | None = None
    fingerprint: str | None = None
    if request.r2lab_identity is not None:
        identity_reference = normalize_identity_reference(request.r2lab_identity)
        fingerprint = ssh_identity_fingerprint(request.r2lab_identity)
    current = format_utc(now)
    return (
        Profile(
            name=request.profile_name,
            created_at_utc=current,
            updated_at_utc=current,
            slices_username=request.slices_username,
            r2lab_slice=request.r2lab_slice,
            r2lab_identity=identity_reference,
            r2lab_identity_fingerprint=fingerprint,
        ),
        True,
    )


def plan_initialization(
    request: InitializationRequest,
    *,
    environment: Mapping[str, str] | None = None,
    slices_runner: Runner = subprocess_runner,
    r2lab_runner: Runner = subprocess_runner,
    timeout_seconds: int = 30,
    now: datetime | None = None,
) -> InitializationPlan:
    """Verify all remote access read-only before writing profile or workspace state."""

    root = request.root.expanduser().resolve()
    if workspace_file(root).exists() or workspace_directory(root).exists():
        raise WorkspaceError("SynthRAN workspace state already exists in this directory")
    current = (now or utc_now()).astimezone(timezone.utc)
    profile, profile_created = _profile_from_request(
        request, environment=environment, now=current
    )
    if profile.slices_username is None:
        raise WorkspaceError("selected profile has no SLICES username")

    slices_access = probe_slices_project_access(
        username=profile.slices_username,
        project=request.project,
        runner=slices_runner,
        timeout_seconds=timeout_seconds,
        now=current,
    )

    r2lab_access: AccessRecord | None = None
    if profile.r2lab_slice is not None or profile.r2lab_identity is not None:
        if profile.r2lab_slice is None or profile.r2lab_identity is None:
            raise WorkspaceError("selected profile has incomplete R2Lab identity data")
        r2lab_access = probe_r2lab_gateway_access(
            slice_name=profile.r2lab_slice,
            identity_reference=profile.r2lab_identity,
            runner=r2lab_runner,
            timeout_seconds=timeout_seconds,
            now=current,
        )
        if r2lab_access.identity_fingerprint != profile.r2lab_identity_fingerprint:
            raise WorkspaceError(
                "verified R2Lab identity does not match the profile fingerprint"
            )

    return InitializationPlan(
        request=request,
        profile=profile,
        slices_access=slices_access,
        r2lab_access=r2lab_access,
        profile_created=profile_created,
    )


def persist_initialization(
    plan: InitializationPlan,
    *,
    environment: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> InitializationResult:
    """Persist a previously verified plan and roll back only state created here on failure."""

    request = plan.request
    root = request.root.expanduser().resolve()
    workspace_path = workspace_directory(root)
    if workspace_path.exists():
        raise WorkspaceError("SynthRAN workspace state appeared after initialization planning")
    profile_file = profile_path(request.profile_name, environment=environment)
    if plan.profile_created and profile_file.exists():
        raise WorkspaceError("SynthRAN profile appeared after initialization planning")

    profile_written = False
    try:
        if plan.profile_created:
            save_profile(plan.profile, environment=environment)
            profile_written = True
        else:
            current_profile = load_profile(
                request.profile_name, environment=environment
            )
            if current_profile != plan.profile:
                raise WorkspaceError(
                    "existing profile changed after initialization planning"
                )

        workspace = initialize_workspace(
            root=root,
            profile=request.profile_name,
            project=request.project,
            reservation_minutes=request.reservation_minutes,
            placement=request.placement,
            now=now,
        )
        save_access_record(root, plan.slices_access)
        if plan.r2lab_access is not None:
            save_access_record(root, plan.r2lab_access)
    except Exception:
        if workspace_path.exists():
            shutil.rmtree(workspace_path)
        if profile_written and profile_file.exists():
            profile_file.unlink()
        raise

    return InitializationResult(
        profile=plan.profile,
        workspace=workspace,
        slices_access=plan.slices_access,
        r2lab_access=plan.r2lab_access,
        profile_created=plan.profile_created,
    )


def initialize_controller_workspace(
    request: InitializationRequest,
    *,
    environment: Mapping[str, str] | None = None,
    slices_runner: Runner = subprocess_runner,
    r2lab_runner: Runner = subprocess_runner,
    timeout_seconds: int = 30,
    now: datetime | None = None,
) -> InitializationResult:
    """Verify stable controller access first, then create one persistent workspace."""

    current = (now or utc_now()).astimezone(timezone.utc)
    plan = plan_initialization(
        request,
        environment=environment,
        slices_runner=slices_runner,
        r2lab_runner=r2lab_runner,
        timeout_seconds=timeout_seconds,
        now=current,
    )
    return persist_initialization(
        plan,
        environment=environment,
        now=current,
    )
