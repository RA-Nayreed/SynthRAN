"""Persistent identity, workspace, access, and experiment data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Mapping


PROFILE_SCHEMA = "synthran/profile/v1alpha1"
WORKSPACE_SCHEMA = "synthran/workspace/v1alpha1"
ACCESS_SCHEMA = "synthran/access/v1alpha1"
EXPERIMENT_SCHEMA = "synthran/experiment-record/v1alpha1"
EXPERIMENT_STATUS_SCHEMA = "synthran/experiment-status/v1alpha1"
RUN_RECORD_SCHEMA = "synthran/run-record/v1alpha1"
OPERATION_RECORD_SCHEMA = "synthran/operation-record/v1alpha1"
ACTIVE_SCHEMA = "synthran/active-experiment/v1alpha1"

PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
EXPERIMENT_ID_RE = re.compile(r"^sran-[0-9]{8}-[0-9]{3,}$")
RUN_ID_RE = re.compile(r"^run-(?P<ordinal>[0-9]{3,})(?:-(?P<label>[a-z0-9][a-z0-9-]{0,47}))?$")
OPERATION_ID_RE = re.compile(r"^op-(?P<ordinal>[0-9]{6,})$")
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]+={0,2}$")


class WorkspaceError(RuntimeError):
    """Raised when persistent SynthRAN state is missing, malformed, or unsafe."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise WorkspaceError("timestamps must be timezone-aware")
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkspaceError(f"{label} is not a valid UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise WorkspaceError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_profile_name(value: str) -> str:
    if not PROFILE_NAME_RE.fullmatch(value):
        raise WorkspaceError(
            "profile name must start with a lowercase letter or number and contain only lowercase letters, numbers, '.', '_', or '-'"
        )
    return value


def validate_safe_name(value: str, label: str) -> str:
    if not SAFE_NAME_RE.fullmatch(value):
        raise WorkspaceError(
            f"{label} must contain only letters, numbers, '.', '_', ':', or '-'"
        )
    return value


def validate_experiment_id(value: str) -> str:
    if not EXPERIMENT_ID_RE.fullmatch(value):
        raise WorkspaceError("experiment ID must use sran-YYYYMMDD-NNN")
    return value


def validate_run_id(value: str) -> str:
    if not RUN_ID_RE.fullmatch(value):
        raise WorkspaceError("run ID must use run-NNN or run-NNN-label")
    return value


def validate_operation_id(value: str) -> str:
    if not OPERATION_ID_RE.fullmatch(value):
        raise WorkspaceError("operation ID must use op-NNNNNN")
    return value


def parse_run_id(value: str) -> tuple[int, str | None]:
    match = RUN_ID_RE.fullmatch(value)
    if match is None:
        raise WorkspaceError("run ID must use run-NNN or run-NNN-label")
    return int(match.group("ordinal")), match.group("label")


def parse_operation_id(value: str) -> int:
    match = OPERATION_ID_RE.fullmatch(value)
    if match is None:
        raise WorkspaceError("operation ID must use op-NNNNNN")
    return int(match.group("ordinal"))


@dataclass(frozen=True)
class Profile:
    """Durable controller identity references; private key material is never stored."""

    name: str
    created_at_utc: str
    updated_at_utc: str
    slices_username: str | None = None
    r2lab_slice: str | None = None
    r2lab_identity: str | None = None
    r2lab_identity_fingerprint: str | None = None
    schema: str = PROFILE_SCHEMA

    def __post_init__(self) -> None:
        validate_profile_name(self.name)
        parse_utc(self.created_at_utc, "profile created_at_utc")
        parse_utc(self.updated_at_utc, "profile updated_at_utc")
        if self.schema != PROFILE_SCHEMA:
            raise WorkspaceError("profile schema is unsupported")
        if self.slices_username is not None:
            validate_safe_name(self.slices_username, "SLICES username")
        if self.r2lab_slice is not None:
            validate_safe_name(self.r2lab_slice, "R2Lab slice")
        if (self.r2lab_identity is None) != (self.r2lab_identity_fingerprint is None):
            raise WorkspaceError(
                "R2Lab identity path and fingerprint must either both be set or both be absent"
            )
        if (
            self.r2lab_identity_fingerprint is not None
            and FINGERPRINT_RE.fullmatch(self.r2lab_identity_fingerprint) is None
        ):
            raise WorkspaceError("R2Lab identity fingerprint is malformed")


@dataclass(frozen=True)
class WorkspaceConfig:
    """Durable research-workspace selection and operator defaults."""

    profile: str
    project: str
    created_at_utc: str
    reservation_minutes: int = 120
    placement: str = "automatic"
    ownership: str = "strict"
    schema: str = WORKSPACE_SCHEMA

    def __post_init__(self) -> None:
        validate_profile_name(self.profile)
        validate_safe_name(self.project, "SLICES project")
        parse_utc(self.created_at_utc, "workspace created_at_utc")
        if self.schema != WORKSPACE_SCHEMA:
            raise WorkspaceError("workspace schema is unsupported")
        if self.reservation_minutes < 10 or self.reservation_minutes > 1440:
            raise WorkspaceError("reservation_minutes must be between 10 and 1440")
        if self.placement not in {"automatic", "manual"}:
            raise WorkspaceError("placement must be automatic or manual")
        if self.ownership != "strict":
            raise WorkspaceError("only strict ownership policy is supported")


@dataclass(frozen=True)
class AccessRecord:
    """Cached read-only authorization evidence with an explicit refresh boundary."""

    provider: str
    subject: str
    scope: str
    verified_at_utc: str
    refresh_after_utc: str
    access_until_utc: str | None = None
    identity_fingerprint: str | None = None
    detail: str = "verified"
    schema: str = ACCESS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != ACCESS_SCHEMA:
            raise WorkspaceError("access record schema is unsupported")
        if self.provider not in {"slices", "r2lab"}:
            raise WorkspaceError("access provider must be slices or r2lab")
        validate_safe_name(self.subject, "access subject")
        validate_safe_name(self.scope, "access scope")
        verified = parse_utc(self.verified_at_utc, "access verified_at_utc")
        refresh = parse_utc(self.refresh_after_utc, "access refresh_after_utc")
        if refresh <= verified:
            raise WorkspaceError("access refresh_after_utc must be after verification")
        if self.access_until_utc is not None:
            until = parse_utc(self.access_until_utc, "access access_until_utc")
            if until <= verified:
                raise WorkspaceError("access_until_utc must be after verification")
            if refresh > until:
                raise WorkspaceError("access refresh boundary cannot exceed provider expiry")
        if (
            self.identity_fingerprint is not None
            and FINGERPRINT_RE.fullmatch(self.identity_fingerprint) is None
        ):
            raise WorkspaceError("access identity fingerprint is malformed")

    def is_fresh(self, now: datetime | None = None) -> bool:
        current = (now or utc_now()).astimezone(timezone.utc)
        refresh = parse_utc(self.refresh_after_utc, "access refresh_after_utc")
        if current >= refresh:
            return False
        if self.access_until_utc is None:
            return True
        return current < parse_utc(self.access_until_utc, "access access_until_utc")

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.access_until_utc is None:
            return False
        current = (now or utc_now()).astimezone(timezone.utc)
        return current >= parse_utc(self.access_until_utc, "access access_until_utc")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "provider": self.provider,
            "subject": self.subject,
            "scope": self.scope,
            "verified_at_utc": self.verified_at_utc,
            "refresh_after_utc": self.refresh_after_utc,
            "access_until_utc": self.access_until_utc,
            "identity_fingerprint": self.identity_fingerprint,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "AccessRecord":
        required = (
            "provider",
            "subject",
            "scope",
            "verified_at_utc",
            "refresh_after_utc",
        )
        if any(not isinstance(value.get(key), str) for key in required):
            raise WorkspaceError("access record is malformed")
        access_until = value.get("access_until_utc")
        if access_until is not None and not isinstance(access_until, str):
            raise WorkspaceError("access record expiry is malformed")
        identity_fingerprint = value.get("identity_fingerprint")
        if identity_fingerprint is not None and not isinstance(identity_fingerprint, str):
            raise WorkspaceError("access identity fingerprint is malformed")
        detail = value.get("detail", "verified")
        if not isinstance(detail, str):
            raise WorkspaceError("access record detail is malformed")
        return cls(
            schema=str(value.get("schema", "")),
            provider=str(value["provider"]),
            subject=str(value["subject"]),
            scope=str(value["scope"]),
            verified_at_utc=str(value["verified_at_utc"]),
            refresh_after_utc=str(value["refresh_after_utc"]),
            access_until_utc=access_until,
            identity_fingerprint=identity_fingerprint,
            detail=detail,
        )


@dataclass(frozen=True)
class ExperimentRecord:
    """Immutable requested configuration identity for one SynthRAN experiment."""

    experiment_id: str
    created_at_utc: str
    profile: str
    project: str
    label: str | None = None
    slices_experiment: str | None = None
    network_intent: str = "unspecified"
    radio_mode: str = "automatic"
    schema: str = EXPERIMENT_SCHEMA

    def __post_init__(self) -> None:
        validate_experiment_id(self.experiment_id)
        parse_utc(self.created_at_utc, "experiment created_at_utc")
        validate_profile_name(self.profile)
        validate_safe_name(self.project, "experiment project")
        if self.schema != EXPERIMENT_SCHEMA:
            raise WorkspaceError("experiment record schema is unsupported")
        if self.slices_experiment is not None:
            validate_safe_name(self.slices_experiment, "SLICES experiment")
        if self.label is not None and (not self.label.strip() or len(self.label) > 120):
            raise WorkspaceError("experiment label must contain 1-120 visible characters")
        if self.network_intent not in {
            "unspecified",
            "virtual-5g",
            "physical-5g",
            "open-ran",
            "iot-to-5g",
        }:
            raise WorkspaceError("experiment network intent is unsupported")
        if self.radio_mode not in {"automatic", "virtual", "physical"}:
            raise WorkspaceError("experiment radio mode is unsupported")


@dataclass(frozen=True)
class ExperimentStatus:
    experiment_id: str
    state: str
    updated_at_utc: str
    provider_checked_at_utc: str | None = None
    provider_state: str = "unknown"
    notes: tuple[str, ...] = field(default_factory=tuple)
    schema: str = EXPERIMENT_STATUS_SCHEMA

    def __post_init__(self) -> None:
        validate_experiment_id(self.experiment_id)
        parse_utc(self.updated_at_utc, "experiment status updated_at_utc")
        if self.schema != EXPERIMENT_STATUS_SCHEMA:
            raise WorkspaceError("experiment status schema is unsupported")
        if self.state not in {
            "issued",
            "configured",
            "active",
            "expired",
            "closed",
            "failed",
        }:
            raise WorkspaceError("experiment status state is unsupported")
        if self.provider_checked_at_utc is not None:
            parse_utc(
                self.provider_checked_at_utc,
                "experiment status provider_checked_at_utc",
            )
        if self.provider_state not in {
            "unknown",
            "active",
            "expired",
            "missing",
            "unreachable",
        }:
            raise WorkspaceError("experiment provider state is unsupported")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "experiment_id": self.experiment_id,
            "state": self.state,
            "updated_at_utc": self.updated_at_utc,
            "provider_checked_at_utc": self.provider_checked_at_utc,
            "provider_state": self.provider_state,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class RunRecord:
    """Durable identity metadata for one measurement run within an experiment."""

    experiment_id: str
    run_id: str
    ordinal: int
    created_at_utc: str
    label: str | None = None
    schema: str = RUN_RECORD_SCHEMA

    def __post_init__(self) -> None:
        validate_experiment_id(self.experiment_id)
        parsed_ordinal, parsed_label = parse_run_id(self.run_id)
        parse_utc(self.created_at_utc, "run created_at_utc")
        if self.schema != RUN_RECORD_SCHEMA:
            raise WorkspaceError("run record schema is unsupported")
        if self.ordinal != parsed_ordinal:
            raise WorkspaceError("run ordinal does not match run ID")
        if self.label != parsed_label:
            raise WorkspaceError("run label does not match run ID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "ordinal": self.ordinal,
            "label": self.label,
            "created_at_utc": self.created_at_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "RunRecord":
        if not isinstance(value.get("ordinal"), int):
            raise WorkspaceError("run record ordinal is malformed")
        label = value.get("label")
        if label is not None and not isinstance(label, str):
            raise WorkspaceError("run record label is malformed")
        return cls(
            schema=str(value.get("schema", "")),
            experiment_id=str(value.get("experiment_id", "")),
            run_id=str(value.get("run_id", "")),
            ordinal=int(value["ordinal"]),
            label=label,
            created_at_utc=str(value.get("created_at_utc", "")),
        )


@dataclass(frozen=True)
class OperationRecord:
    """Durable identity metadata for one workspace control operation."""

    operation_id: str
    ordinal: int
    kind: str
    created_at_utc: str
    experiment_id: str | None = None
    schema: str = OPERATION_RECORD_SCHEMA

    def __post_init__(self) -> None:
        parsed_ordinal = parse_operation_id(self.operation_id)
        parse_utc(self.created_at_utc, "operation created_at_utc")
        if self.schema != OPERATION_RECORD_SCHEMA:
            raise WorkspaceError("operation record schema is unsupported")
        if self.ordinal != parsed_ordinal:
            raise WorkspaceError("operation ordinal does not match operation ID")
        if not self.kind or len(self.kind) > 64 or any(
            not (character.isalnum() or character in "._-") for character in self.kind
        ):
            raise WorkspaceError("operation kind contains unsafe characters")
        if self.experiment_id is not None:
            validate_experiment_id(self.experiment_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "operation_id": self.operation_id,
            "ordinal": self.ordinal,
            "kind": self.kind,
            "experiment_id": self.experiment_id,
            "created_at_utc": self.created_at_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "OperationRecord":
        if not isinstance(value.get("ordinal"), int):
            raise WorkspaceError("operation record ordinal is malformed")
        experiment_id = value.get("experiment_id")
        if experiment_id is not None and not isinstance(experiment_id, str):
            raise WorkspaceError("operation record experiment ID is malformed")
        return cls(
            schema=str(value.get("schema", "")),
            operation_id=str(value.get("operation_id", "")),
            ordinal=int(value["ordinal"]),
            kind=str(value.get("kind", "")),
            experiment_id=experiment_id,
            created_at_utc=str(value.get("created_at_utc", "")),
        )
