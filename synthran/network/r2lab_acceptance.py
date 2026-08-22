"""Monotonic evidence model for physical R2Lab acceptance.

A physical backend must not collapse cell acquisition, registration, PDU
session, user plane, and workload execution into one boolean.  Smoke 002 reached
lower-layer bring-up while the UE never acquired a cell.  This state model makes
those boundaries explicit and prevents a later stage from being marked passed
when an earlier prerequisite was not accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
    """Immutable ordered evidence for one physical acceptance attempt."""

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
