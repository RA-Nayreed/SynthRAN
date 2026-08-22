"""Conservative runtime-state parsing for qfit COTS UEs.

The physical acceptance ladder needs separate evidence for cell acquisition,
registration, and packet/PDU state.  These parsers intentionally do not execute
AT or MBIM commands; they classify already-collected command output so the live
adapter can remain responsible for transport, timeout, and redaction.

Unknown or conflicting observations stay unknown.  User-plane acceptance is not
inferred from registration or an address alone; it requires a separate traffic
probe at a later stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import ipaddress
import re


class QfitRuntimeStateError(ValueError):
    """Raised when qfit runtime evidence is malformed or contradictory."""


class CellAcquisitionState(str, Enum):
    ACQUIRED_NR_SA = "acquired-nr-sa"
    NO_SERVICE = "no-service"
    OTHER_SERVICE = "other-service"
    UNKNOWN = "unknown"


class RegistrationState(str, Enum):
    REGISTERED = "registered"
    SEARCHING = "searching"
    NOT_REGISTERED = "not-registered"
    UNKNOWN = "unknown"


class PacketServiceState(str, Enum):
    ATTACHED = "attached"
    DETACHED = "detached"
    UNKNOWN = "unknown"


class Ipv4State(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


_C5GREG_RE = re.compile(r"\+C5GREG:\s*\d+\s*,\s*(\d+)", re.IGNORECASE)
_PACKET_RE = re.compile(
    r"packet\s+service\s+state\s*:\s*['\"]?(attached|detached)['\"]?",
    re.IGNORECASE,
)
_INET_RE = re.compile(r"\binet\s+([^\s/]+)/\d+\b", re.IGNORECASE)


def parse_qnwinfo(output: str) -> CellAcquisitionState:
    """Classify Quectel ``AT+QNWINFO`` output for the NR-SA checkpoint."""

    normalized = output.upper()
    if "NO SERVICE" in normalized:
        return CellAcquisitionState.NO_SERVICE
    if "NR5G-SA" in normalized or "NR5G_SA" in normalized:
        return CellAcquisitionState.ACQUIRED_NR_SA
    if "+QNWINFO:" in normalized:
        return CellAcquisitionState.OTHER_SERVICE
    return CellAcquisitionState.UNKNOWN


def parse_c5greg(output: str) -> RegistrationState:
    """Parse 5G registration status while failing closed on conflicting values."""

    statuses = [int(match.group(1)) for match in _C5GREG_RE.finditer(output)]
    if not statuses:
        return RegistrationState.UNKNOWN
    unique = set(statuses)
    if len(unique) != 1:
        return RegistrationState.UNKNOWN
    status = statuses[-1]
    if status in {1, 5}:
        return RegistrationState.REGISTERED
    if status == 2:
        return RegistrationState.SEARCHING
    if status in {0, 3, 4}:
        return RegistrationState.NOT_REGISTERED
    return RegistrationState.UNKNOWN


def parse_packet_service(output: str) -> PacketServiceState:
    """Parse MBIM packet-service state without trusting command return code."""

    states = {match.group(1).lower() for match in _PACKET_RE.finditer(output)}
    if not states:
        return PacketServiceState.UNKNOWN
    if len(states) != 1:
        return PacketServiceState.UNKNOWN
    return (
        PacketServiceState.ATTACHED
        if "attached" in states
        else PacketServiceState.DETACHED
    )


def parse_ipv4_state(output: str, *, interface_present: bool = True) -> Ipv4State:
    """Classify sanitized ``ip -4`` output for the selected modem interface."""

    if not interface_present:
        return Ipv4State.UNKNOWN
    addresses = []
    for match in _INET_RE.finditer(output):
        try:
            address = ipaddress.ip_address(match.group(1))
        except ValueError:
            continue
        if isinstance(address, ipaddress.IPv4Address):
            addresses.append(address)
    return Ipv4State.PRESENT if addresses else Ipv4State.ABSENT


@dataclass(frozen=True)
class QfitRuntimeEvidence:
    """Sanitized state used to advance the ordered physical acceptance ladder."""

    cell: CellAcquisitionState
    registration: RegistrationState
    packet_service: PacketServiceState
    ipv4: Ipv4State

    @property
    def cell_acquired(self) -> bool:
        return self.cell is CellAcquisitionState.ACQUIRED_NR_SA

    @property
    def registered(self) -> bool:
        return self.cell_acquired and self.registration is RegistrationState.REGISTERED

    @property
    def pdu_session_established(self) -> bool:
        return (
            self.registered
            and self.packet_service is PacketServiceState.ATTACHED
            and self.ipv4 is Ipv4State.PRESENT
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "cell": self.cell.value,
            "registration": self.registration.value,
            "packet_service": self.packet_service.value,
            "ipv4": self.ipv4.value,
            "cell_acquired": self.cell_acquired,
            "registered": self.registered,
            "pdu_session_established": self.pdu_session_established,
            "user_plane": "requires-separate-traffic-probe",
        }
