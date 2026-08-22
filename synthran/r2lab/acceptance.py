"""Monotonic and persistent evidence model for physical R2Lab acceptance."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Mapping

from synthran.network.runtime import validate_run_id


PHYSICAL_RUN_EVIDENCE_SCHEMA = "synthran/r2lab-physical-run-evidence/v1alpha1"


class R2LabAcceptanceError(ValueError):
    """Raised when physical acceptance evidence violates stage ordering."""


class AcceptanceOutcome(str, Enum):
    NOT_REACHED = "not-reached"
    PASSED = "passed"
    FAILED = "failed"


class PhysicalAcceptanceStage(str, Enum):
    RESOURCE_AUTHORITY = "resource-authority"
    SLICES_FOUNDATION = "slices-foundation"
    KUBERNETES = "kubernetes"
    OPEN5GS = "open5gs"
    GNB_N2 = "gnb-n2"
    UE_MANAGEMENT = "ue-management"
    CELL_ACQUISITION = "cell-acquisition"
    REGISTRATION = "registration"
    PDU_SESSION = "pdu-session"
    USER_PLANE = "user-plane"
    WORKLOAD = "workload"


STAGE_ORDER = (
    PhysicalAcceptanceStage.RESOURCE_AUTHORITY,
    PhysicalAcceptanceStage.SLICES_FOUNDATION,
    PhysicalAcceptanceStage.KUBERNETES,
    PhysicalAcceptanceStage.OPEN5GS,
    PhysicalAcceptanceStage.GNB_N2,
    PhysicalAcceptanceStage.UE_MANAGEMENT,
    PhysicalAcceptanceStage.CELL_ACQUISITION,
    PhysicalAcceptanceStage.REGISTRATION,
    PhysicalAcceptanceStage.PDU_SESSION,
    PhysicalAcceptanceStage.USER_PLANE,
    PhysicalAcceptanceStage.WORKLOAD,
)


@dataclass(frozen=True)
class AcceptanceEvidence:
    stage: PhysicalAcceptanceStage
    outcome: AcceptanceOutcome
    source: str

    def __post_init__(self) -> None:
        if self.outcome is AcceptanceOutcome.NOT_REACHED:
            raise R2LabAcceptanceError(
                "stored acceptance evidence must be passed or failed, not not-reached"
            )
        if not self.source or len(self.source) > 128:
            raise R2LabAcceptanceError("acceptance evidence source must be 1-128 characters")

    def to_dict(self) -> dict[str, str]:
        return {
            "stage": self.stage.value,
            "outcome": self.outcome.value,
            "source": self.source,
        }


@dataclass(frozen=True)
class PhysicalAcceptance:
    evidence: tuple[AcceptanceEvidence, ...] = ()

    def __post_init__(self) -> None:
        failed_seen = False
        for index, item in enumerate(self.evidence):
            if index >= len(STAGE_ORDER) or item.stage is not STAGE_ORDER[index]:
                raise R2LabAcceptanceError(
                    "physical acceptance evidence must be contiguous and ordered"
                )
            if failed_seen:
                raise R2LabAcceptanceError(
                    "physical acceptance cannot contain evidence after a failed stage"
                )
            if item.outcome is AcceptanceOutcome.FAILED:
                failed_seen = True

    @property
    def next_stage(self) -> PhysicalAcceptanceStage | None:
        if self.evidence and self.evidence[-1].outcome is AcceptanceOutcome.FAILED:
            return None
        if len(self.evidence) == len(STAGE_ORDER):
            return None
        return STAGE_ORDER[len(self.evidence)]

    @property
    def accepted(self) -> bool:
        return (
            len(self.evidence) == len(STAGE_ORDER)
            and self.evidence[-1].stage is PhysicalAcceptanceStage.WORKLOAD
            and self.evidence[-1].outcome is AcceptanceOutcome.PASSED
        )

    @property
    def failed_stage(self) -> PhysicalAcceptanceStage | None:
        for item in self.evidence:
            if item.outcome is AcceptanceOutcome.FAILED:
                return item.stage
        return None

    def record(
        self,
        *,
        stage: PhysicalAcceptanceStage,
        outcome: AcceptanceOutcome,
        source: str,
    ) -> "PhysicalAcceptance":
        expected = self.next_stage
        if expected is None:
            raise R2LabAcceptanceError(
                "physical acceptance is already complete or blocked by failure"
            )
        if stage is not expected:
            raise R2LabAcceptanceError(
                f"next physical acceptance stage is {expected.value}, not {stage.value}"
            )
        if outcome is AcceptanceOutcome.NOT_REACHED:
            raise R2LabAcceptanceError("not-reached is derived state, not recorded evidence")
        return PhysicalAcceptance(
            self.evidence + (AcceptanceEvidence(stage, outcome, source),)
        )

    def pass_stage(
        self, stage: PhysicalAcceptanceStage, *, source: str
    ) -> "PhysicalAcceptance":
        return self.record(stage=stage, outcome=AcceptanceOutcome.PASSED, source=source)

    def fail_stage(
        self, stage: PhysicalAcceptanceStage, *, source: str
    ) -> "PhysicalAcceptance":
        return self.record(stage=stage, outcome=AcceptanceOutcome.FAILED, source=source)

    def outcome_for(self, stage: PhysicalAcceptanceStage) -> AcceptanceOutcome:
        index = STAGE_ORDER.index(stage)
        if index < len(self.evidence):
            return self.evidence[index].outcome
        return AcceptanceOutcome.NOT_REACHED

    def to_dict(self) -> dict[str, object]:
        evidence_by_stage = {item.stage: item for item in self.evidence}
        stages = []
        for stage in STAGE_ORDER:
            item = evidence_by_stage.get(stage)
            stages.append(
                {
                    "stage": stage.value,
                    "outcome": (
                        item.outcome.value
                        if item is not None
                        else AcceptanceOutcome.NOT_REACHED.value
                    ),
                    "source": item.source if item is not None else None,
                }
            )
        return {
            "accepted": self.accepted,
            "failed_stage": self.failed_stage.value if self.failed_stage else None,
            "next_stage": self.next_stage.value if self.next_stage else None,
            "stages": stages,
        }


def _validate_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise R2LabAcceptanceError(f"{label} must be a lowercase SHA-256 digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise R2LabAcceptanceError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _canonical_staging_payload(payload: Mapping[str, object]) -> bytes:
    try:
        text = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise R2LabAcceptanceError("staging evidence is not canonical JSON data") from exc
    return text.encode("utf-8")


@dataclass(frozen=True)
class StagedPhysicalEvidence:
    """Immutable binding from reviewed offline artifacts to stopped live staging."""

    run_id: str
    package_sha256: str
    values_sha256: str
    render_sha256: str
    staging_sha256: str

    def __post_init__(self) -> None:
        try:
            validated = validate_run_id(self.run_id)
        except Exception as exc:
            raise R2LabAcceptanceError(str(exc)) from exc
        if validated != self.run_id:
            raise R2LabAcceptanceError("physical evidence run ID is not canonical")
        _validate_sha256(self.package_sha256, "package digest")
        _validate_sha256(self.values_sha256, "values digest")
        _validate_sha256(self.render_sha256, "render digest")
        _validate_sha256(self.staging_sha256, "staging digest")

    @classmethod
    def from_staging_result(
        cls, payload: Mapping[str, object]
    ) -> "StagedPhysicalEvidence":
        run_id = payload.get("run_id")
        if not isinstance(run_id, str):
            raise R2LabAcceptanceError("staging evidence run ID is missing")
        if payload.get("status") != "staged-stopped":
            raise R2LabAcceptanceError("staging evidence is not in staged-stopped state")
        if payload.get("hardware_mutation") is not False:
            raise R2LabAcceptanceError("staging evidence unexpectedly reports hardware mutation")
        if payload.get("namespace_owned") is not True:
            raise R2LabAcceptanceError("staging evidence does not prove namespace ownership")
        if payload.get("desired_replicas") != 0 or payload.get("gnb_pod_count") != 0:
            raise R2LabAcceptanceError("staging evidence does not prove a zero-pod gNB state")

        package_sha256 = _validate_sha256(payload.get("package_sha256"), "package digest")
        values_sha256 = _validate_sha256(payload.get("values_sha256"), "values digest")
        render_sha256 = _validate_sha256(payload.get("render_sha256"), "render digest")
        staging_sha256 = hashlib.sha256(_canonical_staging_payload(payload)).hexdigest()
        return cls(
            run_id=run_id,
            package_sha256=package_sha256,
            values_sha256=values_sha256,
            render_sha256=render_sha256,
            staging_sha256=staging_sha256,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "package_sha256": self.package_sha256,
            "values_sha256": self.values_sha256,
            "render_sha256": self.render_sha256,
            "staging_sha256": self.staging_sha256,
            "status": "staged-stopped",
        }


@dataclass(frozen=True)
class PhysicalRunEvidence:
    """Persistable run evidence that binds deployment hashes to ordered acceptance."""

    run_id: str
    staged: StagedPhysicalEvidence | None = None
    acceptance: PhysicalAcceptance = field(default_factory=PhysicalAcceptance)

    def __post_init__(self) -> None:
        try:
            validated = validate_run_id(self.run_id)
        except Exception as exc:
            raise R2LabAcceptanceError(str(exc)) from exc
        if validated != self.run_id:
            raise R2LabAcceptanceError("physical run evidence ID is not canonical")
        if self.staged is not None and self.staged.run_id != self.run_id:
            raise R2LabAcceptanceError("staged evidence belongs to a different physical run")

    def bind_staging(self, payload: Mapping[str, object]) -> "PhysicalRunEvidence":
        if self.staged is not None:
            raise R2LabAcceptanceError("physical run already has immutable staging evidence")
        staged = StagedPhysicalEvidence.from_staging_result(payload)
        if staged.run_id != self.run_id:
            raise R2LabAcceptanceError("staging evidence belongs to a different physical run")
        return PhysicalRunEvidence(
            run_id=self.run_id,
            staged=staged,
            acceptance=self.acceptance,
        )

    def pass_stage(
        self, stage: PhysicalAcceptanceStage, *, source: str
    ) -> "PhysicalRunEvidence":
        return PhysicalRunEvidence(
            run_id=self.run_id,
            staged=self.staged,
            acceptance=self.acceptance.pass_stage(stage, source=source),
        )

    def fail_stage(
        self, stage: PhysicalAcceptanceStage, *, source: str
    ) -> "PhysicalRunEvidence":
        return PhysicalRunEvidence(
            run_id=self.run_id,
            staged=self.staged,
            acceptance=self.acceptance.fail_stage(stage, source=source),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": PHYSICAL_RUN_EVIDENCE_SCHEMA,
            "run_id": self.run_id,
            "staged": self.staged.to_dict() if self.staged is not None else None,
            "acceptance": self.acceptance.to_dict(),
        }

    def write_json(self, path: Path) -> Path:
        path = path.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary_path = Path(temporary.name)
            temporary_path.replace(path)
        except OSError as exc:
            raise R2LabAcceptanceError("physical run evidence could not be persisted") from exc
        return path
