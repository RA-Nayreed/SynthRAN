"""User-facing status projections derived from durable and observed state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from synthran.workspace.model import WorkspaceError


@dataclass(frozen=True)
class DimensionView:
    name: str
    state: str
    fresh: bool
    source: str | None = None
    ownership: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.name or len(self.name) > 64:
            raise WorkspaceError("status dimension name is malformed")
        if not self.state or len(self.state) > 64:
            raise WorkspaceError("status dimension state is malformed")
        if len(self.detail) > 512:
            raise WorkspaceError("status dimension detail is too long")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "state": self.state,
            "fresh": self.fresh,
            "source": self.source,
            "ownership": self.ownership,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ApplicationSnapshot:
    workspace_root: str
    profile: str
    project: str
    experiment_id: str | None
    provider_experiment: str | None
    intent: str | None
    radio_mode: str | None
    lifecycle: str
    observations: tuple[DimensionView, ...] = ()
    next_steps: tuple[str, ...] = ()
    blocks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.lifecycle not in {
            "EMPTY",
            "CONFIGURED",
            "RESERVED",
            "ALLOCATED",
            "PREPARED",
            "NETWORK_READY",
            "PATH_PROVEN",
            "EXPERIMENT_RUNNING",
            "RECOVERY_REQUIRED",
            "BLOCKED",
        }:
            raise WorkspaceError("application lifecycle is unsupported")
        if any(not value or len(value) > 64 for value in self.next_steps):
            raise WorkspaceError("application next step is malformed")
        if any(not value or len(value) > 512 for value in self.blocks):
            raise WorkspaceError("application block reason is malformed")

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace_root": self.workspace_root,
            "profile": self.profile,
            "project": self.project,
            "experiment_id": self.experiment_id,
            "provider_experiment": self.provider_experiment,
            "intent": self.intent,
            "radio_mode": self.radio_mode,
            "lifecycle": self.lifecycle,
            "observations": [item.to_dict() for item in self.observations],
            "next_steps": list(self.next_steps),
            "blocks": list(self.blocks),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ApplicationSnapshot":
        raw_observations = value.get("observations", [])
        if not isinstance(raw_observations, list):
            raise WorkspaceError("application observations are malformed")
        observations: list[DimensionView] = []
        for item in raw_observations:
            if not isinstance(item, Mapping):
                raise WorkspaceError("application observation entry is malformed")
            observations.append(
                DimensionView(
                    name=str(item.get("name", "")),
                    state=str(item.get("state", "")),
                    fresh=item.get("fresh") is True,
                    source=(
                        str(item["source"])
                        if item.get("source") is not None
                        else None
                    ),
                    ownership=(
                        str(item["ownership"])
                        if item.get("ownership") is not None
                        else None
                    ),
                    detail=str(item.get("detail", "")),
                )
            )
        next_steps = value.get("next_steps", [])
        blocks = value.get("blocks", [])
        if not isinstance(next_steps, list) or not all(
            isinstance(item, str) for item in next_steps
        ):
            raise WorkspaceError("application next steps are malformed")
        if not isinstance(blocks, list) or not all(isinstance(item, str) for item in blocks):
            raise WorkspaceError("application blocks are malformed")
        return cls(
            workspace_root=str(value.get("workspace_root", "")),
            profile=str(value.get("profile", "")),
            project=str(value.get("project", "")),
            experiment_id=(
                str(value["experiment_id"])
                if value.get("experiment_id") is not None
                else None
            ),
            provider_experiment=(
                str(value["provider_experiment"])
                if value.get("provider_experiment") is not None
                else None
            ),
            intent=(str(value["intent"]) if value.get("intent") is not None else None),
            radio_mode=(
                str(value["radio_mode"])
                if value.get("radio_mode") is not None
                else None
            ),
            lifecycle=str(value.get("lifecycle", "")),
            observations=tuple(observations),
            next_steps=tuple(next_steps),
            blocks=tuple(blocks),
        )
