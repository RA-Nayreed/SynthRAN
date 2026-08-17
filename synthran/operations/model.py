"""Operation plans, approvals, state, events, and execution permits."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from synthran.workspace.model import (
    WorkspaceError,
    parse_utc,
    validate_experiment_id,
    validate_operation_id,
)


OPERATION_PLAN_SCHEMA = "synthran/operation-plan/v1alpha1"
OPERATION_STATE_SCHEMA = "synthran/operation-state/v1alpha1"
APPROVAL_SCHEMA = "synthran/approval/v1alpha1"
OPERATION_EVENT_SCHEMA = "synthran/operation-event/v1alpha1"

RISK_CLASSES = frozenset({"R0", "R1", "R2", "R3"})
OPERATION_STATUSES = frozenset(
    {
        "planned",
        "awaiting-approval",
        "approved",
        "running",
        "completed",
        "failed",
        "recovery-required",
    }
)
APPROVAL_MODES = frozenset({"standard", "destructive"})
EVENT_TYPES = frozenset(
    {
        "operation.started",
        "plan.created",
        "approval.requested",
        "approval.granted",
        "operation.authorized",
        "operation.completed",
        "operation.failed",
        "operation.interrupted",
        "recovery.required",
    }
)
HEX_DIGEST_LENGTH = 64


def _validate_digest(value: str, label: str) -> str:
    if len(value) != HEX_DIGEST_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise WorkspaceError(f"{label} must be a lowercase SHA256 digest")
    return value


def _validate_kind(value: str) -> str:
    if not value or len(value) > 64 or any(
        not (character.isalnum() or character in "._-") for character in value
    ):
        raise WorkspaceError("operation kind contains unsafe characters")
    return value


def _validate_reason(value: str) -> str:
    if not value or len(value) > 512 or any(character in "\x00" for character in value):
        raise WorkspaceError("operation reason is malformed")
    return value


@dataclass(frozen=True)
class OperationPlan:
    operation_id: str
    experiment_id: str
    kind: str
    risk: str
    mutates: bool
    reason: str
    desired_sha256: str
    observed_sha256: str
    reconciliation_sha256: str
    plan_sha256: str
    created_at_utc: str
    schema: str = OPERATION_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != OPERATION_PLAN_SCHEMA:
            raise WorkspaceError("operation plan schema is unsupported")
        validate_operation_id(self.operation_id)
        validate_experiment_id(self.experiment_id)
        _validate_kind(self.kind)
        if self.risk not in RISK_CLASSES:
            raise WorkspaceError("operation risk class is unsupported")
        if self.mutates and self.risk not in {"R2", "R3"}:
            raise WorkspaceError("mutating operation must use R2 or R3")
        if not self.mutates and self.risk not in {"R0", "R1"}:
            raise WorkspaceError("non-mutating operation must use R0 or R1")
        _validate_reason(self.reason)
        _validate_digest(self.desired_sha256, "desired state digest")
        _validate_digest(self.observed_sha256, "observed state digest")
        _validate_digest(self.reconciliation_sha256, "reconciliation digest")
        _validate_digest(self.plan_sha256, "operation plan digest")
        parse_utc(self.created_at_utc, "operation plan created_at_utc")

    @property
    def approval_required(self) -> bool:
        return self.risk in {"R2", "R3"}

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "operation_id": self.operation_id,
            "experiment_id": self.experiment_id,
            "kind": self.kind,
            "risk": self.risk,
            "mutates": self.mutates,
            "reason": self.reason,
            "desired_sha256": self.desired_sha256,
            "observed_sha256": self.observed_sha256,
            "reconciliation_sha256": self.reconciliation_sha256,
            "created_at_utc": self.created_at_utc,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.unsigned_dict(), "plan_sha256": self.plan_sha256}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "OperationPlan":
        return cls(
            schema=str(value.get("schema", "")),
            operation_id=str(value.get("operation_id", "")),
            experiment_id=str(value.get("experiment_id", "")),
            kind=str(value.get("kind", "")),
            risk=str(value.get("risk", "")),
            mutates=value.get("mutates") is True,
            reason=str(value.get("reason", "")),
            desired_sha256=str(value.get("desired_sha256", "")),
            observed_sha256=str(value.get("observed_sha256", "")),
            reconciliation_sha256=str(value.get("reconciliation_sha256", "")),
            plan_sha256=str(value.get("plan_sha256", "")),
            created_at_utc=str(value.get("created_at_utc", "")),
        )


@dataclass(frozen=True)
class ApprovalGrant:
    operation_id: str
    plan_sha256: str
    risk: str
    mode: str
    approved_at_utc: str
    schema: str = APPROVAL_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != APPROVAL_SCHEMA:
            raise WorkspaceError("approval schema is unsupported")
        validate_operation_id(self.operation_id)
        _validate_digest(self.plan_sha256, "approval plan digest")
        if self.risk not in {"R2", "R3"}:
            raise WorkspaceError("approval is valid only for R2 or R3 operations")
        if self.mode not in APPROVAL_MODES:
            raise WorkspaceError("approval mode is unsupported")
        if self.risk == "R3" and self.mode != "destructive":
            raise WorkspaceError("R3 operation requires destructive approval")
        parse_utc(self.approved_at_utc, "approval approved_at_utc")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "operation_id": self.operation_id,
            "plan_sha256": self.plan_sha256,
            "risk": self.risk,
            "mode": self.mode,
            "approved_at_utc": self.approved_at_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ApprovalGrant":
        return cls(
            schema=str(value.get("schema", "")),
            operation_id=str(value.get("operation_id", "")),
            plan_sha256=str(value.get("plan_sha256", "")),
            risk=str(value.get("risk", "")),
            mode=str(value.get("mode", "")),
            approved_at_utc=str(value.get("approved_at_utc", "")),
        )


@dataclass(frozen=True)
class OperationState:
    operation_id: str
    status: str
    risk: str
    mutates: bool
    plan_sha256: str
    updated_at_utc: str
    claim_held: bool = False
    schema: str = OPERATION_STATE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != OPERATION_STATE_SCHEMA:
            raise WorkspaceError("operation state schema is unsupported")
        validate_operation_id(self.operation_id)
        if self.status not in OPERATION_STATUSES:
            raise WorkspaceError("operation status is unsupported")
        if self.risk not in RISK_CLASSES:
            raise WorkspaceError("operation state risk is unsupported")
        _validate_digest(self.plan_sha256, "operation state plan digest")
        parse_utc(self.updated_at_utc, "operation state updated_at_utc")
        if self.claim_held and not self.mutates:
            raise WorkspaceError("read-only operation cannot hold a mutation claim")
        if self.status == "completed" and self.claim_held:
            raise WorkspaceError("completed operation cannot retain a mutation claim")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "operation_id": self.operation_id,
            "status": self.status,
            "risk": self.risk,
            "mutates": self.mutates,
            "plan_sha256": self.plan_sha256,
            "updated_at_utc": self.updated_at_utc,
            "claim_held": self.claim_held,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "OperationState":
        return cls(
            schema=str(value.get("schema", "")),
            operation_id=str(value.get("operation_id", "")),
            status=str(value.get("status", "")),
            risk=str(value.get("risk", "")),
            mutates=value.get("mutates") is True,
            plan_sha256=str(value.get("plan_sha256", "")),
            updated_at_utc=str(value.get("updated_at_utc", "")),
            claim_held=value.get("claim_held") is True,
        )


@dataclass(frozen=True)
class OperationEvent:
    operation_id: str
    sequence: int
    event_type: str
    occurred_at_utc: str
    risk: str
    mutates: bool
    plan_sha256: str
    attributes: Mapping[str, str] = field(default_factory=dict)
    schema: str = OPERATION_EVENT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != OPERATION_EVENT_SCHEMA:
            raise WorkspaceError("operation event schema is unsupported")
        validate_operation_id(self.operation_id)
        if self.sequence < 1:
            raise WorkspaceError("operation event sequence must be positive")
        if self.event_type not in EVENT_TYPES:
            raise WorkspaceError("operation event type is unsupported")
        parse_utc(self.occurred_at_utc, "operation event occurred_at_utc")
        if self.risk not in RISK_CLASSES:
            raise WorkspaceError("operation event risk is unsupported")
        _validate_digest(self.plan_sha256, "operation event plan digest")
        clean: dict[str, str] = {}
        for key, value in self.attributes.items():
            if not key or len(key) > 64 or any(
                not (character.isalnum() or character in "._-") for character in key
            ):
                raise WorkspaceError("operation event attribute key is unsafe")
            if not isinstance(value, str) or len(value) > 256 or any(
                character in "\r\n\x00" for character in value
            ):
                raise WorkspaceError("operation event attribute value is unsafe")
            clean[key] = value
        object.__setattr__(self, "attributes", clean)

    @property
    def event_id(self) -> str:
        return f"{self.operation_id}:{self.sequence:04d}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "event_id": self.event_id,
            "operation_id": self.operation_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "occurred_at_utc": self.occurred_at_utc,
            "risk": self.risk,
            "mutates": self.mutates,
            "plan_sha256": self.plan_sha256,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class ExecutionPermit:
    """Ephemeral authorization handed to a provider executor after all gates pass."""

    operation_id: str
    experiment_id: str
    kind: str
    risk: str
    mutates: bool
    plan_sha256: str
    issued_at_utc: str

    def __post_init__(self) -> None:
        validate_operation_id(self.operation_id)
        validate_experiment_id(self.experiment_id)
        _validate_kind(self.kind)
        if self.risk not in RISK_CLASSES:
            raise WorkspaceError("execution permit risk is unsupported")
        _validate_digest(self.plan_sha256, "execution permit plan digest")
        parse_utc(self.issued_at_utc, "execution permit issued_at_utc")
