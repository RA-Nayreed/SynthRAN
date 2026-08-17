"""Persistent SynthRAN identity, workspace, access, and experiment services."""

from synthran.workspace.access import (
    verify_r2lab_gateway_access,
    verify_slices_project_access,
)
from synthran.workspace.model import (
    AccessRecord,
    ExperimentRecord,
    ExperimentStatus,
    Profile,
    WorkspaceConfig,
    WorkspaceError,
)
from synthran.workspace.registry import ExperimentEntry, WorkspaceRegistry
from synthran.workspace.store import (
    DEFAULT_PROFILE_NAME,
    create_or_update_profile,
    find_workspace_root,
    initialize_workspace,
    load_access_record,
    load_active_experiment_id,
    load_experiment_record,
    load_profile,
    load_workspace,
    profile_path,
    resolve_identity_reference,
    set_active_experiment,
    verify_profile_identity,
)

__all__ = [
    "AccessRecord",
    "DEFAULT_PROFILE_NAME",
    "ExperimentEntry",
    "ExperimentRecord",
    "ExperimentStatus",
    "Profile",
    "WorkspaceConfig",
    "WorkspaceError",
    "WorkspaceRegistry",
    "create_or_update_profile",
    "find_workspace_root",
    "initialize_workspace",
    "load_access_record",
    "load_active_experiment_id",
    "load_experiment_record",
    "load_profile",
    "load_workspace",
    "profile_path",
    "resolve_identity_reference",
    "set_active_experiment",
    "verify_profile_identity",
    "verify_r2lab_gateway_access",
    "verify_slices_project_access",
]
