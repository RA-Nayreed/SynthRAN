"""Observed testbed facts, freshness, ownership, and truth selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping

from synthran.workspace.model import WorkspaceError, format_utc, parse_utc, utc_now, validate_experiment_id


OBSERVED_STATE_SCHEMA = "synthran/observed-state/v1alpha1"
OBSERVATION_STATES = frozenset(
    {"unknown", "absent", "pending", "ready", "degraded", "failed", "blocked"}
)
OBSERVATION_SOURCES = frozenset(
    {"provider", "observation", "evidence", "manifest", "cache"}
)
SOURCE_PRIORITY = {
    "provider": 5,
    "observation": 4,
    "evidence": 3,
    "manifest": 2,
    "cache": 1,
}
OWNERSHIP_VALUES = frozenset(
    {"synthran", "operator", "other", "unknown", "unowned"}
)
OBSERVED_DIMENSIONS = (
    "controller",
    "project_access",
    "provider_experiment",
    "reservation",
    "allocation",
    "preparation",
    "kubernetes",
    "core",
    "ran",
    "ue",
    "pdu",
    "upf",
    "radio",
    "r2lab_lease",
    "iot",
    "path",
    "experiment",
    "dataset",
)

JSON_SCALAR = str | int | float | bool | None


def _validate_facts(value: Mapping[str, JSON_SCALAR]) -> Mapping[str, JSON_SCALAR]:
    clean: dict[str, JSON_SCALAR] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > 64:
            raise WorkspaceError("observation fact keys must contain 1-64 characters")
        if type(item) not in {str, int, float, bool, type(None)}:
            raise WorkspaceError("observation facts must contain JSON scalar values")
        if isinstance(item, str) and len(item) > 2048:
            raise WorkspaceError("observation fact text is too long")
        clean[key] = item
    return MappingProxyType(clean)


@dataclass(frozen=True)
class Observation:
    """One fact set from one authority tier at one time."""

    dimension: str
    state: str
    source: str
    observed_at_utc: str
    fresh_until_utc: str | None = None
    ownership: str = "unknown"
    resource_id: str | None = None
    detail: str = ""
    facts: Mapping[str, JSON_SCALAR] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.dimension not in OBSERVED_DIMENSIONS:
            raise WorkspaceError("unsupported observed-state dimension")
        if self.state not in OBSERVATION_STATES:
            raise WorkspaceError("unsupported observation state")
        if self.source not in OBSERVATION_SOURCES:
            raise WorkspaceError("unsupported observation source")
        observed = parse_utc(self.observed_at_utc, "observation observed_at_utc")
        if self.source in {"provider", "observation"} and self.fresh_until_utc is None:
            raise WorkspaceError("live observation requires an explicit freshness boundary")
        if self.fresh_until_utc is not None:
            fresh_until = parse_utc(
                self.fresh_until_utc, "observation fresh_until_utc"
            )
            if fresh_until <= observed:
                raise WorkspaceError("observation freshness must end after observation time")
        if self.ownership not in OWNERSHIP_VALUES:
            raise WorkspaceError("unsupported observation ownership")
        if self.resource_id is not None:
            if not self.resource_id or len(self.resource_id) > 256:
                raise WorkspaceError("observation resource ID is malformed")
            if any(character in "\r\n\x00" for character in self.resource_id):
                raise WorkspaceError("observation resource ID contains unsafe characters")
        if len(self.detail) > 2048:
            raise WorkspaceError("observation detail is too long")
        object.__setattr__(self, "facts", _validate_facts(self.facts))

    def is_fresh(self, now: datetime | None = None) -> bool:
        current = (now or utc_now()).astimezone(timezone.utc)
        if self.fresh_until_utc is None:
            return False
        return current < parse_utc(self.fresh_until_utc, "observation fresh_until_utc")

    @property
    def source_priority(self) -> int:
        return SOURCE_PRIORITY[self.source]

    def permits_automatic_mutation(self, now: datetime | None = None) -> bool:
        """Only current SynthRAN-owned live facts may authorize automatic mutation."""

        return (
            self.ownership == "synthran"
            and self.source in {"provider", "observation"}
            and self.is_fresh(now)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "dimension": self.dimension,
            "state": self.state,
            "source": self.source,
            "observed_at_utc": self.observed_at_utc,
            "fresh_until_utc": self.fresh_until_utc,
            "ownership": self.ownership,
            "resource_id": self.resource_id,
            "detail": self.detail,
            "facts": dict(self.facts),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "Observation":
        facts = value.get("facts", {})
        if not isinstance(facts, Mapping):
            raise WorkspaceError("observation facts are malformed")
        fact_values: dict[str, JSON_SCALAR] = {}
        for key, item in facts.items():
            if not isinstance(key, str):
                raise WorkspaceError("observation fact key is malformed")
            if type(item) not in {str, int, float, bool, type(None)}:
                raise WorkspaceError("observation fact value is malformed")
            fact_values[key] = item  # type: ignore[assignment]
        fresh_until = value.get("fresh_until_utc")
        resource_id = value.get("resource_id")
        return cls(
            dimension=str(value.get("dimension", "")),
            state=str(value.get("state", "")),
            source=str(value.get("source", "")),
            observed_at_utc=str(value.get("observed_at_utc", "")),
            fresh_until_utc=(str(fresh_until) if fresh_until is not None else None),
            ownership=str(value.get("ownership", "unknown")),
            resource_id=(str(resource_id) if resource_id is not None else None),
            detail=str(value.get("detail", "")),
            facts=fact_values,
        )


def select_authoritative_observation(
    observations: tuple[Observation, ...] | list[Observation],
    *,
    now: datetime | None = None,
) -> Observation | None:
    """Apply provider > observation > evidence > manifest > cache to current facts."""

    if not observations:
        return None
    current = (now or utc_now()).astimezone(timezone.utc)
    dimensions = {item.dimension for item in observations}
    if len(dimensions) != 1:
        raise WorkspaceError("truth selection requires one observation dimension")
    fresh = [item for item in observations if item.is_fresh(current)]
    candidates = fresh if fresh else list(observations)
    return max(
        candidates,
        key=lambda item: (
            item.source_priority,
            parse_utc(item.observed_at_utc, "observation observed_at_utc"),
        ),
    )


@dataclass(frozen=True)
class ObservedState:
    """One reconciled snapshot; persisted copies remain observation caches, not authority."""

    experiment_id: str
    collected_at_utc: str
    observations: tuple[Observation, ...]
    schema: str = OBSERVED_STATE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != OBSERVED_STATE_SCHEMA:
            raise WorkspaceError("observed-state schema is unsupported")
        validate_experiment_id(self.experiment_id)
        parse_utc(self.collected_at_utc, "observed state collected_at_utc")
        dimensions = [item.dimension for item in self.observations]
        if len(dimensions) != len(set(dimensions)):
            raise WorkspaceError("observed state may contain only one reconciled fact per dimension")

    def get(self, dimension: str) -> Observation | None:
        if dimension not in OBSERVED_DIMENSIONS:
            raise WorkspaceError("unsupported observed-state dimension")
        for item in self.observations:
            if item.dimension == dimension:
                return item
        return None

    def state(self, dimension: str) -> str:
        item = self.get(dimension)
        return item.state if item is not None else "unknown"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "experiment_id": self.experiment_id,
            "collected_at_utc": self.collected_at_utc,
            "observations": [item.to_dict() for item in self.observations],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ObservedState":
        raw = value.get("observations", [])
        if not isinstance(raw, list):
            raise WorkspaceError("observed-state observations are malformed")
        observations: list[Observation] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise WorkspaceError("observed-state observation entry is malformed")
            observations.append(Observation.from_dict(item))
        return cls(
            schema=str(value.get("schema", "")),
            experiment_id=str(value.get("experiment_id", "")),
            collected_at_utc=str(value.get("collected_at_utc", "")),
            observations=tuple(observations),
        )


def reconcile_observation_sets(
    *,
    experiment_id: str,
    observations: Mapping[str, tuple[Observation, ...] | list[Observation]],
    now: datetime | None = None,
) -> ObservedState:
    """Reduce source-specific observations into one truth-ranked snapshot."""

    current = (now or utc_now()).astimezone(timezone.utc)
    reconciled: list[Observation] = []
    for dimension in OBSERVED_DIMENSIONS:
        candidates = observations.get(dimension, ())
        if any(item.dimension != dimension for item in candidates):
            raise WorkspaceError("observation set contains the wrong dimension")
        selected = select_authoritative_observation(list(candidates), now=current)
        if selected is not None:
            reconciled.append(selected)
    return ObservedState(
        experiment_id=experiment_id,
        collected_at_utc=format_utc(current),
        observations=tuple(reconciled),
    )
