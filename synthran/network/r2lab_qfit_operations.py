"""Verified exact qfit power operations for R2Lab.

The qfit helper performs the selected mutation. SynthRAN then queries the exact
underlying R2Lab reboot node and accepts the transition only when that provider
observation proves the requested state. A mutation timeout does not stop the
status query because the provider may already have acted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from synthran.live_preflight import CommandResult
from synthran.network.r2lab_power import PowerState
from synthran.network.r2lab_qfit import parse_qfit_status, qfit_node_number


RemoteRunner = Callable[[Sequence[str], int], CommandResult]


@dataclass(frozen=True)
class VerifiedQfitOperation:
    qfit: str
    requested_state: PowerState
    observed_state: PowerState
    mutation_returncode: int | None
    status_returncode: int | None
    mutation_transport_error: bool
    status_transport_error: bool

    @property
    def confirmed(self) -> bool:
        return self.observed_state is self.requested_state

    @property
    def unresolved(self) -> bool:
        return not self.confirmed

    def to_dict(self) -> dict[str, object]:
        return {
            "qfit": self.qfit,
            "requested_state": self.requested_state.value,
            "observed_state": self.observed_state.value,
            "confirmed": self.confirmed,
            "mutation_returncode": self.mutation_returncode,
            "status_returncode": self.status_returncode,
            "mutation_transport_error": self.mutation_transport_error,
            "status_transport_error": self.status_transport_error,
        }


def execute_verified_qfit_transition(
    *,
    qfit: str,
    requested_state: PowerState,
    runner: RemoteRunner,
    timeout_seconds: int,
) -> VerifiedQfitOperation:
    """Mutate one qfit and verify its exact R2Lab reboot-node state."""

    if requested_state is PowerState.UNKNOWN:
        raise ValueError("UNKNOWN cannot be requested as a qfit target state")

    node = qfit_node_number(qfit)
    action = "on" if requested_state is PowerState.ON else "off"

    mutation_returncode: int | None = None
    mutation_transport_error = False
    try:
        mutation = runner(("qfit", action, qfit), timeout_seconds)
    except (RuntimeError, OSError):
        mutation_transport_error = True
    else:
        mutation_returncode = mutation.returncode

    status_returncode: int | None = None
    status_stdout = ""
    status_stderr = ""
    status_transport_error = False
    try:
        status = runner(("rhubarbe", "status", str(node)), timeout_seconds)
    except (RuntimeError, OSError):
        status_transport_error = True
    else:
        status_returncode = status.returncode
        status_stdout = status.stdout
        status_stderr = status.stderr

    observation = parse_qfit_status(
        "\n".join(part for part in (status_stdout, status_stderr) if part),
        qfit=qfit,
    )
    return VerifiedQfitOperation(
        qfit=observation.qfit,
        requested_state=requested_state,
        observed_state=observation.state,
        mutation_returncode=mutation_returncode,
        status_returncode=status_returncode,
        mutation_transport_error=mutation_transport_error,
        status_transport_error=status_transport_error,
    )
