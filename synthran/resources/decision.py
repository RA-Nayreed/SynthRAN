"""Resource placement decisions suitable for immutable operation binding."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from synthran.resources.model import (
    ResourceInventory,
    ResourceSelection,
    ResourceSelectionError,
    ResourceState,
)
from synthran.resources.selector import select_resources
from synthran.workspace.desired import ExperimentDesiredState


@dataclass(frozen=True)
class ResourceDecision:
    """Exact placement plus current state of every selected resource."""

    selection: ResourceSelection
    states: tuple[ResourceState, ...]

    def __post_init__(self) -> None:
        selected = {item.resource_id for item in self.selection.assignments}
        observed = {item.resource_id for item in self.states}
        if selected != observed:
            raise ResourceSelectionError(
                "resource decision states do not match the selected resource set"
            )
        if len(observed) != len(self.states):
            raise ResourceSelectionError("resource decision contains duplicate states")
        if any(not item.selectable for item in self.states):
            raise ResourceSelectionError(
                "resource decision cannot bind an unsafe current resource state"
            )

    @property
    def targets(self) -> tuple[str, ...]:
        return tuple(
            sorted(item.resource_id for item in self.selection.assignments)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "selection": self.selection.to_dict(),
            "states": [
                {
                    "resource_id": item.resource_id,
                    "availability": item.availability,
                    "ownership": item.ownership,
                }
                for item in self.states
            ],
        }


def build_resource_decision(
    desired: ExperimentDesiredState,
    inventory: ResourceInventory,
    *,
    now: datetime | None = None,
) -> ResourceDecision:
    """Select resources and bind the current state that made each one selectable."""

    selection = select_resources(desired, inventory, now=now)
    states: list[ResourceState] = []
    for resource_id in sorted(
        item.resource_id for item in selection.assignments
    ):
        state = inventory.state(resource_id)
        if state is None:
            raise ResourceSelectionError(
                f"selected resource {resource_id} lost its current provider state"
            )
        states.append(state)
    return ResourceDecision(selection=selection, states=tuple(states))
