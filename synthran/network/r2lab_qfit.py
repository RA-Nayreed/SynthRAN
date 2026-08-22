"""Exact qfit power-state parsing for the R2Lab provider.

qfit helpers are convenient mutation wrappers, but SynthRAN still needs an
independent provider observation before it can call a qfit resource clean or
ready. Live smoke 002 used ``rhubarbe status 7`` to verify ``qfit07`` as
``reboot07:off`` after the exact qfit power-off operation.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from synthran.network.r2lab_power import PowerState


class R2LabQfitStateError(RuntimeError):
    """Raised when a qfit identifier or provider observation is malformed."""


_QFIT_PATTERN = re.compile(r"^qfit(?P<node>\d{2})$")


@dataclass(frozen=True)
class QfitStatusObservation:
    """One exact qfit node power observation."""

    qfit: str
    node: int
    state: PowerState


def qfit_node_number(qfit: str) -> int:
    """Return the R2Lab node number encoded by a qfit resource name."""

    value = qfit.strip().lower()
    match = _QFIT_PATTERN.fullmatch(value)
    if match is None:
        raise R2LabQfitStateError("qfit resource must use the qfitNN form")
    node = int(match.group("node"))
    if node <= 0:
        raise R2LabQfitStateError("qfit node number must be positive")
    return node


def parse_qfit_status(output: str, *, qfit: str) -> QfitStatusObservation:
    """Parse exact ``rebootNN:on|off`` state for one qfit resource.

    Other reboot nodes are ignored. Missing state remains ``UNKNOWN`` and
    conflicting observations fail closed.
    """

    value = qfit.strip().lower()
    node = qfit_node_number(value)
    token = f"reboot{node:02d}"
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_-]){re.escape(token)}\s*:\s*(on|off)(?![A-Za-z0-9_-])",
        re.IGNORECASE,
    )

    states: list[PowerState] = []
    for line in output.splitlines():
        match = pattern.search(line)
        if match is None:
            continue
        states.append(PowerState.ON if match.group(1).lower() == "on" else PowerState.OFF)

    if not states:
        return QfitStatusObservation(qfit=value, node=node, state=PowerState.UNKNOWN)

    unique = set(states)
    if len(unique) != 1:
        raise R2LabQfitStateError(f"conflicting R2Lab qfit state observations for {value}")

    return QfitStatusObservation(qfit=value, node=node, state=states[-1])
