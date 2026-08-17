"""Deterministic capability-based placement over current provider inventory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations

from synthran.resources.model import (
    ProviderResourceSet,
    ResourceAssignment,
    ResourceDescriptor,
    ResourceInventory,
    ResourceRequirement,
    ResourceSelection,
    ResourceSelectionError,
    ResourceState,
)
from synthran.resources.requirements import requirements_from_desired
from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import utc_now


@dataclass(frozen=True)
class _Candidate:
    descriptor: ResourceDescriptor
    state: ResourceState


def _require_snapshot(
    inventory: ResourceInventory,
    provider: str,
    *,
    now: datetime,
) -> None:
    if provider == "virtual":
        return
    snapshot = inventory.snapshot(provider)
    if snapshot is None:
        raise ResourceSelectionError(
            f"current complete {provider} resource inventory is required"
        )
    if not snapshot.complete:
        raise ResourceSelectionError(
            f"partial {provider} resource inventory cannot drive placement"
        )
    if not snapshot.is_fresh(now):
        raise ResourceSelectionError(
            f"{provider} resource inventory is stale and must be refreshed"
        )


def _candidate(
    inventory: ResourceInventory,
    descriptor: ResourceDescriptor,
) -> _Candidate | None:
    state = inventory.state(descriptor.resource_id)
    if state is None or not state.selectable:
        return None
    return _Candidate(descriptor, state)


def _eligible(
    requirement: ResourceRequirement,
    inventory: ResourceInventory,
    *,
    now: datetime,
) -> tuple[_Candidate, ...]:
    if requirement.provider is not None:
        _require_snapshot(inventory, requirement.provider, now=now)

    if requirement.pinned_ids:
        selected: list[_Candidate] = []
        for resource_id in requirement.pinned_ids:
            descriptor = inventory.descriptor(resource_id)
            if descriptor is None:
                raise ResourceSelectionError(
                    f"pinned resource {resource_id} has no reviewed capability descriptor"
                )
            _require_snapshot(inventory, descriptor.provider, now=now)
            if requirement.provider is not None and descriptor.provider != requirement.provider:
                raise ResourceSelectionError(
                    f"pinned resource {resource_id} is on the wrong provider"
                )
            if requirement.kind is not None and descriptor.kind != requirement.kind:
                raise ResourceSelectionError(
                    f"pinned resource {resource_id} has the wrong resource kind"
                )
            if not descriptor.supports(requirement.capabilities):
                raise ResourceSelectionError(
                    f"pinned resource {resource_id} does not satisfy {requirement.role} capabilities"
                )
            candidate = _candidate(inventory, descriptor)
            if candidate is None:
                state = inventory.state(resource_id)
                if state is None:
                    raise ResourceSelectionError(
                        f"pinned resource {resource_id} is absent from current provider inventory"
                    )
                if state.ownership in {"other", "unknown"}:
                    raise ResourceSelectionError(
                        f"pinned resource {resource_id} has unsafe ownership"
                    )
                raise ResourceSelectionError(
                    f"pinned resource {resource_id} is not currently selectable"
                )
            selected.append(candidate)
        return tuple(selected)

    selected = []
    for descriptor in inventory.descriptors:
        if requirement.provider is not None and descriptor.provider != requirement.provider:
            continue
        if requirement.kind is not None and descriptor.kind != requirement.kind:
            continue
        if not descriptor.supports(requirement.capabilities):
            continue
        candidate = _candidate(inventory, descriptor)
        if candidate is not None:
            selected.append(candidate)
    if len(selected) < requirement.count:
        raise ResourceSelectionError(
            f"no safe current resource set satisfies role {requirement.role}"
        )
    return tuple(selected)


def _rank(candidate: _Candidate, role: str) -> tuple[int, int, str]:
    ownership = {"synthran": 0, "operator": 1, "unowned": 2}[
        candidate.state.ownership
    ]
    return (
        ownership,
        candidate.descriptor.priority_for(role),
        candidate.descriptor.resource_id,
    )


def _options(
    requirement: ResourceRequirement,
    inventory: ResourceInventory,
    *,
    now: datetime,
) -> tuple[tuple[_Candidate, ...], ...]:
    candidates = _eligible(requirement, inventory, now=now)
    if requirement.pinned_ids:
        return (candidates,)
    ordered = tuple(sorted(candidates, key=lambda item: _rank(item, requirement.role)))
    return tuple(combinations(ordered, requirement.count))


def _score(
    assignments: tuple[tuple[ResourceRequirement, tuple[_Candidate, ...]], ...],
) -> tuple[int, int, int, int, tuple[str, ...]]:
    chosen = [
        (requirement.role, candidate)
        for requirement, candidates in assignments
        for candidate in candidates
    ]
    unowned = sum(candidate.state.ownership == "unowned" for _, candidate in chosen)
    operator_owned = sum(
        candidate.state.ownership == "operator" for _, candidate in chosen
    )
    priority = sum(
        candidate.descriptor.priority_for(role) for role, candidate in chosen
    )
    distinct = len({candidate.descriptor.resource_id for _, candidate in chosen})
    lexical = tuple(
        candidate.descriptor.resource_id
        for role, candidate in sorted(
            chosen,
            key=lambda item: (item[0], item[1].descriptor.resource_id),
        )
    )
    return (unowned, operator_owned, priority, distinct, lexical)


def select_resources(
    desired: ExperimentDesiredState,
    inventory: ResourceInventory,
    *,
    now: datetime | None = None,
) -> ResourceSelection:
    """Select a safe resource set without contacting or changing any provider."""

    current = (now or utc_now()).astimezone(timezone.utc)
    requirements = requirements_from_desired(desired)
    choices = [
        (requirement, _options(requirement, inventory, now=current))
        for requirement in requirements
    ]
    solutions: list[
        tuple[tuple[ResourceRequirement, tuple[_Candidate, ...]], ...]
    ] = []

    def walk(
        index: int,
        used: frozenset[str],
        chosen: tuple[tuple[ResourceRequirement, tuple[_Candidate, ...]], ...],
    ) -> None:
        if index == len(choices):
            solutions.append(chosen)
            return
        requirement, requirement_options = choices[index]
        for candidate_set in requirement_options:
            identifiers = frozenset(
                candidate.descriptor.resource_id for candidate in candidate_set
            )
            if identifiers & used:
                continue
            walk(
                index + 1,
                used | identifiers,
                chosen + ((requirement, candidate_set),),
            )

    walk(0, frozenset(), ())
    if not solutions:
        raise ResourceSelectionError(
            "no compatible non-overlapping resource set satisfies the requested experiment"
        )
    winner = min(solutions, key=_score)

    assignments: list[ResourceAssignment] = []
    for requirement, candidates in winner:
        ordered = (
            candidates
            if requirement.pinned_ids
            else tuple(sorted(candidates, key=lambda item: _rank(item, requirement.role)))
        )
        for ordinal, candidate in enumerate(ordered, start=1):
            assignments.append(
                ResourceAssignment(
                    role=requirement.role,
                    ordinal=ordinal,
                    resource_id=candidate.descriptor.resource_id,
                    provider=candidate.descriptor.provider,
                    kind=candidate.descriptor.kind,
                    ownership=candidate.state.ownership,
                )
            )

    assignments.sort(key=lambda item: (item.role, item.ordinal, item.resource_id))
    grouped: dict[str, list[str]] = {}
    for assignment in assignments:
        grouped.setdefault(assignment.provider, []).append(assignment.resource_id)
    provider_sets = tuple(
        ProviderResourceSet(provider, tuple(sorted(resource_ids)))
        for provider, resource_ids in sorted(grouped.items())
    )
    return ResourceSelection(tuple(assignments), provider_sets)
