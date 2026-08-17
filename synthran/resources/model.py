"""Provider-neutral resource descriptors, live inventory, requirements, and selections."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping
import re

from synthran.workspace.model import WorkspaceError, parse_utc, utc_now


RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RESOURCE_KINDS = frozenset({"compute", "radio", "ue", "auxiliary", "virtual"})
AVAILABILITY_STATES = frozenset({"available", "allocated", "unavailable", "unknown"})
OWNERSHIP_STATES = frozenset({"synthran", "operator", "other", "unknown", "unowned"})


class ResourceSelectionError(WorkspaceError):
    """Raised when current resource facts cannot satisfy requested placement safely."""


def _token(value: str, label: str) -> str:
    if TOKEN_RE.fullmatch(value) is None:
        raise ResourceSelectionError(f"{label} contains unsupported characters")
    return value


def _resource_id(value: str) -> str:
    if RESOURCE_ID_RE.fullmatch(value) is None:
        raise ResourceSelectionError("resource ID contains unsupported characters")
    return value


@dataclass(frozen=True)
class ResourceDescriptor:
    """Stable capability metadata; this record never claims current availability."""

    resource_id: str
    provider: str
    kind: str
    capabilities: frozenset[str]
    role_priority: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _resource_id(self.resource_id)
        _token(self.provider, "resource provider")
        if self.kind not in RESOURCE_KINDS:
            raise ResourceSelectionError("resource kind is unsupported")
        if not self.capabilities:
            raise ResourceSelectionError("resource descriptor requires capabilities")
        for capability in self.capabilities:
            _token(capability, "resource capability")
        priorities: dict[str, int] = {}
        for role, priority in self.role_priority.items():
            _token(role, "resource role")
            if type(priority) is not int or priority < 0 or priority > 10_000:
                raise ResourceSelectionError("resource role priority must be 0-10000")
            priorities[role] = priority
        object.__setattr__(self, "role_priority", MappingProxyType(priorities))

    def supports(self, required: frozenset[str]) -> bool:
        return required.issubset(self.capabilities)

    def priority_for(self, role: str) -> int:
        return self.role_priority.get(role, 1000)


@dataclass(frozen=True)
class ResourceState:
    """Current provider fact for one resource; no stable capability metadata is stored here."""

    resource_id: str
    availability: str
    ownership: str

    def __post_init__(self) -> None:
        _resource_id(self.resource_id)
        if self.availability not in AVAILABILITY_STATES:
            raise ResourceSelectionError("resource availability state is unsupported")
        if self.ownership not in OWNERSHIP_STATES:
            raise ResourceSelectionError("resource ownership state is unsupported")
        if self.availability == "available" and self.ownership not in {
            "unowned",
            "synthran",
            "operator",
        }:
            raise ResourceSelectionError(
                "available resource must have known safe ownership state"
            )
        if self.availability == "allocated" and self.ownership == "unowned":
            raise ResourceSelectionError("allocated resource cannot be unowned")

    @property
    def selectable(self) -> bool:
        return (
            self.availability in {"available", "allocated"}
            and self.ownership in {"synthran", "operator", "unowned"}
        )


@dataclass(frozen=True)
class ProviderResourceSnapshot:
    """Complete or partial current inventory returned by one provider query."""

    provider: str
    observed_at_utc: str
    fresh_until_utc: str
    complete: bool
    resources: tuple[ResourceState, ...]

    def __post_init__(self) -> None:
        _token(self.provider, "snapshot provider")
        observed = parse_utc(self.observed_at_utc, "resource inventory observed_at_utc")
        fresh_until = parse_utc(
            self.fresh_until_utc, "resource inventory fresh_until_utc"
        )
        if fresh_until <= observed:
            raise ResourceSelectionError(
                "resource inventory freshness must end after observation time"
            )
        identifiers = [resource.resource_id for resource in self.resources]
        if len(identifiers) != len(set(identifiers)):
            raise ResourceSelectionError("provider inventory contains duplicate resources")

    def is_fresh(self, now: datetime | None = None) -> bool:
        current = (now or utc_now()).astimezone(timezone.utc)
        return current < parse_utc(
            self.fresh_until_utc, "resource inventory fresh_until_utc"
        )

    def state(self, resource_id: str) -> ResourceState | None:
        for item in self.resources:
            if item.resource_id == resource_id:
                return item
        return None


@dataclass(frozen=True)
class ResourceInventory:
    """Stable descriptors plus provider snapshots used for one selection calculation."""

    descriptors: tuple[ResourceDescriptor, ...]
    snapshots: tuple[ProviderResourceSnapshot, ...]

    def __post_init__(self) -> None:
        descriptor_ids = [item.resource_id for item in self.descriptors]
        if len(descriptor_ids) != len(set(descriptor_ids)):
            raise ResourceSelectionError("resource descriptors contain duplicate IDs")
        providers = [item.provider for item in self.snapshots]
        if len(providers) != len(set(providers)):
            raise ResourceSelectionError("resource inventory contains duplicate provider snapshots")
        descriptor_by_id = {item.resource_id: item for item in self.descriptors}
        for snapshot in self.snapshots:
            for state in snapshot.resources:
                descriptor = descriptor_by_id.get(state.resource_id)
                if descriptor is not None and descriptor.provider != snapshot.provider:
                    raise ResourceSelectionError(
                        "provider inventory resource conflicts with stable descriptor provider"
                    )

    def descriptor(self, resource_id: str) -> ResourceDescriptor | None:
        for item in self.descriptors:
            if item.resource_id == resource_id:
                return item
        return None

    def snapshot(self, provider: str) -> ProviderResourceSnapshot | None:
        for item in self.snapshots:
            if item.provider == provider:
                return item
        return None

    def state(self, resource_id: str) -> ResourceState | None:
        descriptor = self.descriptor(resource_id)
        if descriptor is None:
            return None
        if descriptor.provider == "virtual":
            return ResourceState(resource_id, "available", "unowned")
        snapshot = self.snapshot(descriptor.provider)
        return snapshot.state(resource_id) if snapshot is not None else None


@dataclass(frozen=True)
class ResourceRequirement:
    role: str
    provider: str | None
    kind: str | None
    capabilities: frozenset[str] = frozenset()
    count: int = 1
    pinned_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _token(self.role, "resource requirement role")
        if self.provider is not None:
            _token(self.provider, "resource requirement provider")
        if self.kind is not None and self.kind not in RESOURCE_KINDS:
            raise ResourceSelectionError("resource requirement kind is unsupported")
        for capability in self.capabilities:
            _token(capability, "resource requirement capability")
        if self.count < 1 or self.count > 256:
            raise ResourceSelectionError("resource requirement count must be 1-256")
        if self.pinned_ids:
            if len(self.pinned_ids) != self.count:
                raise ResourceSelectionError(
                    "pinned resource count must match requirement count"
                )
            if len(set(self.pinned_ids)) != len(self.pinned_ids):
                raise ResourceSelectionError("pinned resource IDs must be unique")
            for resource_id in self.pinned_ids:
                _resource_id(resource_id)


@dataclass(frozen=True)
class ResourceAssignment:
    role: str
    ordinal: int
    resource_id: str
    provider: str
    kind: str
    ownership: str

    def __post_init__(self) -> None:
        _token(self.role, "resource assignment role")
        if self.ordinal < 1:
            raise ResourceSelectionError("resource assignment ordinal must be positive")
        _resource_id(self.resource_id)
        _token(self.provider, "resource assignment provider")
        if self.kind not in RESOURCE_KINDS:
            raise ResourceSelectionError("resource assignment kind is unsupported")
        if self.ownership not in OWNERSHIP_STATES:
            raise ResourceSelectionError("resource assignment ownership is unsupported")

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "ordinal": self.ordinal,
            "resource_id": self.resource_id,
            "provider": self.provider,
            "kind": self.kind,
            "ownership": self.ownership,
        }


@dataclass(frozen=True)
class ProviderResourceSet:
    provider: str
    resource_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _token(self.provider, "provider resource-set provider")
        if not self.resource_ids:
            raise ResourceSelectionError("provider resource set must not be empty")
        if len(set(self.resource_ids)) != len(self.resource_ids):
            raise ResourceSelectionError("provider resource set contains duplicates")
        for resource_id in self.resource_ids:
            _resource_id(resource_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "resource_ids": list(self.resource_ids),
        }


@dataclass(frozen=True)
class ResourceSelection:
    """Deterministic provider-neutral placement; it is not mutation authority."""

    assignments: tuple[ResourceAssignment, ...]
    provider_sets: tuple[ProviderResourceSet, ...]

    def __post_init__(self) -> None:
        resource_ids = [item.resource_id for item in self.assignments]
        if len(resource_ids) != len(set(resource_ids)):
            raise ResourceSelectionError(
                "one physical resource cannot satisfy multiple placement assignments"
            )
        grouped: dict[str, set[str]] = {}
        for assignment in self.assignments:
            grouped.setdefault(assignment.provider, set()).add(assignment.resource_id)
        declared = {
            item.provider: set(item.resource_ids) for item in self.provider_sets
        }
        if grouped != declared:
            raise ResourceSelectionError(
                "provider resource sets do not match resource assignments"
            )

    def for_role(self, role: str) -> tuple[ResourceAssignment, ...]:
        return tuple(item for item in self.assignments if item.role == role)

    def to_dict(self) -> dict[str, object]:
        return {
            "assignments": [item.to_dict() for item in self.assignments],
            "provider_sets": [item.to_dict() for item in self.provider_sets],
        }
