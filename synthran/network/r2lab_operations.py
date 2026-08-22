"""Exact-resource R2Lab provider operations derived from live smoke evidence.

This module deliberately operates on remote-command tuples instead of building
SSH itself. The higher-level resource controller remains responsible for lease
authority and strict Faraday transport. Keeping this layer small makes the live
provider semantics independently testable before wiring them into prepare,
release, and recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from synthran.live_preflight import CommandResult
from synthran.network.r2lab_power import (
    PduTransitionEvidence,
    PowerState,
    R2LabPowerStateError,
    evaluate_pdu_transition,
)


RemoteRunner = Callable[[Sequence[str], int], CommandResult]


@dataclass(frozen=True)
class VerifiedPduOperation:
    """Result of one exact mutation followed by one exact status query."""

    evidence: PduTransitionEvidence
    mutation_transport_error: bool
    status_transport_error: bool

    @property
    def confirmed(self) -> bool:
        return self.evidence.confirmed

    @property
    def unresolved(self) -> bool:
        return not self.confirmed

    def to_dict(self) -> dict[str, object]:
        return {
            "resource": self.evidence.resource,
            "requested_state": self.evidence.requested_state.value,
            "observed_state": self.evidence.observed_state.value,
            "confirmed": self.confirmed,
            "mutation_returncode": self.evidence.mutation_returncode,
            "status_returncode": self.evidence.status_returncode,
            "mutation_transport_error": self.mutation_transport_error,
            "status_transport_error": self.status_transport_error,
            "watts": self.evidence.watts,
        }


def execute_verified_pdu_transition(
    *,
    resource: str,
    requested_state: PowerState,
    runner: RemoteRunner,
    timeout_seconds: int,
) -> VerifiedPduOperation:
    """Mutate one PDU-backed resource and verify its exact textual state.

    A mutation transport failure does not end the observation sequence because
    the provider may already have acted. SynthRAN immediately queries the exact
    resource state. A status transport failure or missing/contradictory state
    leaves the result unresolved; callers must retain the resource claim.

    Lease authority is intentionally not handled here. The caller must check it
    immediately before invoking this function.
    """

    if requested_state is PowerState.UNKNOWN:
        raise R2LabPowerStateError("UNKNOWN cannot be requested as a PDU target state")

    action = "on" if requested_state is PowerState.ON else "off"
    mutation_returncode: int | None = None
    mutation_transport_error = False

    try:
        mutation = runner(
            ("rhubarbe", "pdu", action, resource),
            timeout_seconds,
        )
    except (RuntimeError, OSError):
        mutation_transport_error = True
    else:
        mutation_returncode = mutation.returncode

    status_returncode: int | None = None
    status_stdout = ""
    status_stderr = ""
    status_transport_error = False

    try:
        status = runner(
            ("rhubarbe", "pdu", "status", resource),
            timeout_seconds,
        )
    except (RuntimeError, OSError):
        status_transport_error = True
    else:
        status_returncode = status.returncode
        status_stdout = status.stdout
        status_stderr = status.stderr

    evidence = evaluate_pdu_transition(
        resource=resource,
        requested_state=requested_state,
        mutation_returncode=mutation_returncode,
        status_returncode=status_returncode,
        status_stdout=status_stdout,
        status_stderr=status_stderr,
    )
    return VerifiedPduOperation(
        evidence=evidence,
        mutation_transport_error=mutation_transport_error,
        status_transport_error=status_transport_error,
    )
