"""Small fail-closed state model for R2Lab cleanup and claim release.

The live smoke run demonstrated that cleanup is not equivalent to a sequence of
commands that all returned zero. A physical resource is clean only when the
provider state is proven clean. Unknown or contradictory state keeps the local
claim and recovery continues only against the exact run-owned resources.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class CleanupState(str, Enum):
    """Evidence-backed cleanup state for one selected physical resource."""

    PROVEN_OFF = "proven-off"
    PROVEN_ON = "proven-on"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CleanupEvidence:
    """Sanitized evidence for one release/recovery stage."""

    resource: str
    stage: str
    state: CleanupState
    source: str

    @property
    def clean(self) -> bool:
        return self.state is CleanupState.PROVEN_OFF

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "resource": self.resource,
            "stage": self.stage,
            "state": self.state.value,
            "source": self.source,
            "clean": self.clean,
        }


@dataclass(frozen=True)
class ReleaseAssessment:
    """Claim-release decision derived only from exact resource evidence."""

    evidence: tuple[CleanupEvidence, ...]

    @classmethod
    def build(cls, evidence: Iterable[CleanupEvidence]) -> "ReleaseAssessment":
        return cls(tuple(evidence))

    @property
    def claim_releasable(self) -> bool:
        return bool(self.evidence) and all(item.clean for item in self.evidence)

    @property
    def unresolved_resources(self) -> tuple[str, ...]:
        return tuple(item.resource for item in self.evidence if not item.clean)

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_releasable": self.claim_releasable,
            "unresolved_resources": list(self.unresolved_resources),
            "evidence": [item.to_dict() for item in self.evidence],
        }


def release_assessment(
    *,
    ue: CleanupEvidence,
    radio: CleanupEvidence,
) -> ReleaseAssessment:
    """Assess the two exact physical resources in dependency cleanup order.

    The radio result is required even when UE cleanup is unresolved. This models
    the live recovery rule that one failed cleanup stage must not prevent an
    independent exact-resource cleanup attempt for the other selected resource.
    The local claim is releasable only when both resources are proven off.
    """

    return ReleaseAssessment.build((ue, radio))
