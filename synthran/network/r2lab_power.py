"""Provider-specific R2Lab PDU state parsing and transition verification.

Rhubarbe PDU mutation exit codes are not sufficient evidence of the resulting
hardware state. Live R2Lab acceptance showed a successful ``pdu off`` returning
status 1 while the command output and an immediate status query both reported
``OFF``. SynthRAN therefore treats an exact textual status observation as the
provider truth for a PDU transition and records mutation/status return codes only
as diagnostic evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class R2LabPowerStateError(RuntimeError):
    """Raised when provider PDU state output is contradictory or malformed."""


class PowerState(str, Enum):
    """One observed R2Lab PDU power state."""

    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PduStatusObservation:
    """Parsed state for exactly one R2Lab PDU-backed resource."""

    resource: str
    state: PowerState
    watts: int | None = None


@dataclass(frozen=True)
class PduTransitionEvidence:
    """Evidence for one requested PDU state transition.

    ``mutation_returncode`` is intentionally not used by ``confirmed``. The
    provider's exact status text is the acceptance criterion because Rhubarbe
    may return a non-zero code for a successful OFF transition. ``None`` means
    the transport did not yield a return code, for example after a timeout.
    """

    resource: str
    requested_state: PowerState
    observed_state: PowerState
    mutation_returncode: int | None
    status_returncode: int | None
    watts: int | None = None

    @property
    def confirmed(self) -> bool:
        return self.observed_state is self.requested_state


def _validate_resource_name(resource: str) -> str:
    value = resource.strip().lower()
    if not value or len(value) > 64:
        raise R2LabPowerStateError("R2Lab resource name must contain 1-64 characters")
    if any(not (character.isalnum() or character in "._-") for character in value):
        raise R2LabPowerStateError("R2Lab resource name contains unsafe characters")
    return value


def parse_pdu_status(output: str, *, resource: str) -> PduStatusObservation:
    """Parse the textual Rhubarbe PDU state for exactly ``resource``.

    Expected live output resembles::

        pdu2 chain-0@outlet-1 (n300): OFF
        pdu2 chain-0@outlet-1 (n300): ON (28W)

    Unrelated resources are ignored. No matching line yields ``UNKNOWN``.
    Conflicting observations for the same resource fail closed.
    """

    resource = _validate_resource_name(resource)
    pattern = re.compile(
        rf"\({re.escape(resource)}\)\s*:\s*(ON|OFF)(?:\s*\((\d+)W\))?",
        re.IGNORECASE,
    )

    matches: list[tuple[PowerState, int | None]] = []
    for line in output.splitlines():
        match = pattern.search(line)
        if match is None:
            continue
        state = PowerState.ON if match.group(1).upper() == "ON" else PowerState.OFF
        watts = int(match.group(2)) if match.group(2) is not None else None
        matches.append((state, watts))

    if not matches:
        return PduStatusObservation(resource=resource, state=PowerState.UNKNOWN)

    states = {state for state, _ in matches}
    if len(states) != 1:
        raise R2LabPowerStateError(
            f"conflicting R2Lab PDU state observations for {resource}"
        )

    state, watts = matches[-1]
    return PduStatusObservation(resource=resource, state=state, watts=watts)


def evaluate_pdu_transition(
    *,
    resource: str,
    requested_state: PowerState,
    mutation_returncode: int | None,
    status_returncode: int | None,
    status_stdout: str = "",
    status_stderr: str = "",
) -> PduTransitionEvidence:
    """Evaluate one mutation using an immediate exact-resource status query.

    Both stdout and stderr are parsed because provider wrappers can place useful
    status text on either stream. Either command may lack a return code after a
    transport failure; exact status text can still prove the resulting state.
    Missing or contradictory text never becomes a successful transition.
    """

    if requested_state is PowerState.UNKNOWN:
        raise R2LabPowerStateError("UNKNOWN cannot be requested as a PDU target state")

    combined_status = "\n".join(part for part in (status_stdout, status_stderr) if part)
    observation = parse_pdu_status(combined_status, resource=resource)
    return PduTransitionEvidence(
        resource=observation.resource,
        requested_state=requested_state,
        observed_state=observation.state,
        mutation_returncode=mutation_returncode,
        status_returncode=status_returncode,
        watts=observation.watts,
    )
