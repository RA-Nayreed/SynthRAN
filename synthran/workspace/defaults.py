"""Durable updates for non-authority workspace defaults."""

from __future__ import annotations

from pathlib import Path

from synthran.workspace.model import WorkspaceConfig, WorkspaceError
from synthran.workspace.store import (
    _atomic_text,
    load_workspace,
    workspace_file,
    workspace_to_toml,
)


def update_workspace_defaults(
    root: Path,
    *,
    reservation_minutes: int,
    placement: str,
    expected_reservation_minutes: int,
    expected_placement: str,
) -> WorkspaceConfig:
    """Atomically replace stable defaults after checking caller-observed state."""

    current = load_workspace(root)
    if (
        current.reservation_minutes != expected_reservation_minutes
        or current.placement != expected_placement
    ):
        raise WorkspaceError(
            "workspace defaults changed since they were read; reload before saving"
        )

    updated = WorkspaceConfig(
        schema=current.schema,
        profile=current.profile,
        project=current.project,
        created_at_utc=current.created_at_utc,
        reservation_minutes=reservation_minutes,
        placement=placement,
        ownership=current.ownership,
    )
    _atomic_text(workspace_file(root), workspace_to_toml(updated), mode=0o600)
    return updated
