"""Validated desired configuration for one SynthRAN 5G/Open RAN experiment."""

from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import re
from typing import Mapping, Sequence

from synthran.workspace.model import WorkspaceError


NAMESPACE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
DNN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,61}[a-z0-9])?$")
HEX_SD_RE = re.compile(r"^[0-9A-Fa-f]{6}$")

CORE_IMPLEMENTATIONS = frozenset({"automatic", "open5gs", "oai", "free5gc"})
RAN_IMPLEMENTATIONS = frozenset({"automatic", "srsran", "oai", "ueransim"})
UE_IMPLEMENTATIONS = frozenset({"automatic", "srsue", "oai", "ueransim"})
RADIO_MODES = frozenset({"automatic", "virtual", "physical"})
RADIO_BACKENDS = frozenset({"automatic", "rfsim", "r2lab"})
RADIO_HARDWARE = frozenset({"automatic", "n300", "n320"})
RAN_ARCHITECTURES = frozenset({"automatic", "monolithic", "cu-du"})
PDU_SESSION_TYPES = frozenset({"ipv4", "ipv6", "ipv4v6"})
ADDRESS_POLICIES = frozenset({"discover", "static"})
PLACEMENT_MODES = frozenset({"automatic", "manual"})


def _validate_namespace(value: str, label: str) -> str:
    if NAMESPACE_RE.fullmatch(value) is None:
        raise WorkspaceError(f"{label} must be a valid Kubernetes namespace name")
    return value


def _validate_dnn_name(value: str) -> str:
    if DNN_RE.fullmatch(value) is None:
        raise WorkspaceError("DNN name contains unsupported characters")
    return value


def _ip_address(value: str, label: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise WorkspaceError(f"{label} must be a valid IP address") from exc


def _network(value: str, family: int, label: str) -> str:
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as exc:
        raise WorkspaceError(f"{label} must be a canonical network prefix") from exc
    if network.version != family:
        raise WorkspaceError(f"{label} must be IPv{family}")
    return str(network)


@dataclass(frozen=True)
class CoreDesiredState:
    implementation: str = "automatic"
    namespace: str = "core"
    nrf_address_policy: str = "discover"
    nrf_address: str | None = None

    def __post_init__(self) -> None:
        if self.implementation not in CORE_IMPLEMENTATIONS:
            raise WorkspaceError("unsupported core implementation")
        _validate_namespace(self.namespace, "core namespace")
        if self.nrf_address_policy not in ADDRESS_POLICIES:
            raise WorkspaceError("NRF address policy must be discover or static")
        if self.nrf_address_policy == "discover" and self.nrf_address is not None:
            raise WorkspaceError("discovered NRF address must not be stored as desired state")
        if self.nrf_address_policy == "static":
            if self.nrf_address is None:
                raise WorkspaceError("static NRF address policy requires an address")
            _ip_address(self.nrf_address, "NRF address")


@dataclass(frozen=True)
class RanDesiredState:
    implementation: str = "automatic"
    namespace: str = "ran"
    architecture: str = "automatic"
    gnb_id: int = 0xE01
    f1_enabled: bool = False
    du_enabled: bool = True

    def __post_init__(self) -> None:
        if self.implementation not in RAN_IMPLEMENTATIONS:
            raise WorkspaceError("unsupported RAN implementation")
        _validate_namespace(self.namespace, "RAN namespace")
        if self.architecture not in RAN_ARCHITECTURES:
            raise WorkspaceError("unsupported RAN architecture")
        if self.gnb_id < 0 or self.gnb_id > 0xFFFFFFFF:
            raise WorkspaceError("gNB ID must be between 0 and 0xffffffff")
        if self.architecture == "monolithic" and self.f1_enabled:
            raise WorkspaceError("monolithic RAN cannot request F1")
        if self.architecture == "cu-du" and not self.du_enabled:
            raise WorkspaceError("CU/DU RAN requires a DU")


@dataclass(frozen=True)
class UeDesiredState:
    implementation: str = "automatic"
    namespace: str = "ran"
    count: int = 1

    def __post_init__(self) -> None:
        if self.implementation not in UE_IMPLEMENTATIONS:
            raise WorkspaceError("unsupported UE implementation")
        _validate_namespace(self.namespace, "UE namespace")
        if self.count < 1 or self.count > 256:
            raise WorkspaceError("UE count must be between 1 and 256")


@dataclass(frozen=True)
class RadioDesiredState:
    mode: str = "automatic"
    backend: str = "automatic"
    hardware: str = "automatic"

    def __post_init__(self) -> None:
        if self.mode not in RADIO_MODES:
            raise WorkspaceError("unsupported radio mode")
        if self.backend not in RADIO_BACKENDS:
            raise WorkspaceError("unsupported radio backend")
        if self.hardware not in RADIO_HARDWARE:
            raise WorkspaceError("unsupported radio hardware")
        if self.mode == "virtual" and self.backend == "r2lab":
            raise WorkspaceError("virtual radio mode cannot use R2Lab")
        if self.mode == "virtual" and self.hardware != "automatic":
            raise WorkspaceError("virtual radio mode cannot pin physical hardware")
        if self.mode == "physical" and self.backend == "rfsim":
            raise WorkspaceError("physical radio mode cannot use RFSIM")
        if self.hardware != "automatic" and self.backend not in {"automatic", "r2lab"}:
            raise WorkspaceError("physical radio hardware requires the R2Lab backend")


@dataclass(frozen=True)
class PlmnDesiredState:
    mcc: str = "001"
    mnc: str = "01"
    tac: int = 1

    def __post_init__(self) -> None:
        if len(self.mcc) != 3 or not self.mcc.isdigit():
            raise WorkspaceError("MCC must contain exactly three digits")
        if len(self.mnc) not in {2, 3} or not self.mnc.isdigit():
            raise WorkspaceError("MNC must contain two or three digits")
        if self.tac < 0 or self.tac > 0xFFFFFF:
            raise WorkspaceError("TAC must be between 0 and 0xffffff")


@dataclass(frozen=True)
class DnnDesiredState:
    name: str
    pdu_session_type: str = "ipv4"
    ipv4_subnet: str | None = None
    ipv6_subnet: str | None = None

    def __post_init__(self) -> None:
        _validate_dnn_name(self.name)
        if self.pdu_session_type not in PDU_SESSION_TYPES:
            raise WorkspaceError("unsupported PDU session type")
        if self.ipv4_subnet is not None:
            _network(self.ipv4_subnet, 4, f"DNN {self.name} IPv4 subnet")
        if self.ipv6_subnet is not None:
            _network(self.ipv6_subnet, 6, f"DNN {self.name} IPv6 subnet")
        if self.pdu_session_type == "ipv4":
            if self.ipv4_subnet is None or self.ipv6_subnet is not None:
                raise WorkspaceError("IPv4 DNN requires only an IPv4 subnet")
        elif self.pdu_session_type == "ipv6":
            if self.ipv6_subnet is None or self.ipv4_subnet is not None:
                raise WorkspaceError("IPv6 DNN requires only an IPv6 subnet")
        elif self.ipv4_subnet is None and self.ipv6_subnet is None:
            raise WorkspaceError("IPv4v6 DNN requires at least one configured subnet")


@dataclass(frozen=True)
class SliceDesiredState:
    sst: int
    dnn: str
    sd: str | None = None
    five_qi: int = 9
    ambr_ul_bps: int = 100_000_000
    ambr_dl_bps: int = 100_000_000

    def __post_init__(self) -> None:
        if self.sst < 0 or self.sst > 255:
            raise WorkspaceError("SST must be between 0 and 255")
        _validate_dnn_name(self.dnn)
        if self.sd is not None and HEX_SD_RE.fullmatch(self.sd) is None:
            raise WorkspaceError("SD must contain exactly six hexadecimal digits")
        if self.five_qi < 1 or self.five_qi > 255:
            raise WorkspaceError("5QI must be between 1 and 255")
        if self.ambr_ul_bps <= 0 or self.ambr_dl_bps <= 0:
            raise WorkspaceError("slice AMBR values must be positive")

    @property
    def normalized_sd(self) -> str | None:
        return self.sd.upper() if self.sd is not None else None


@dataclass(frozen=True)
class MultusDesiredState:
    enabled: bool = False
    network: str | None = None
    host_interface: str | None = None

    def __post_init__(self) -> None:
        if not self.enabled and (self.network is not None or self.host_interface is not None):
            raise WorkspaceError("disabled Multus cannot contain network or host-interface settings")
        if self.enabled:
            if self.network is not None:
                _validate_namespace(self.network, "Multus network")
            if self.host_interface is not None and (
                not self.host_interface
                or len(self.host_interface) > 64
                or any(not (ch.isalnum() or ch in "._:-") for ch in self.host_interface)
            ):
                raise WorkspaceError("Multus host interface contains unsafe characters")


@dataclass(frozen=True)
class RicDesiredState:
    enabled: bool = False
    implementation: str = "flexric"

    def __post_init__(self) -> None:
        if self.implementation != "flexric":
            raise WorkspaceError("unsupported RIC implementation")


@dataclass(frozen=True)
class PlacementDesiredState:
    mode: str = "automatic"
    core_node: str | None = None
    ran_node: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in PLACEMENT_MODES:
            raise WorkspaceError("placement mode must be automatic or manual")
        if self.mode == "automatic" and (
            self.core_node is not None or self.ran_node is not None
        ):
            raise WorkspaceError("automatic placement cannot pin compute nodes")
        if self.mode == "manual":
            if self.core_node is None or self.ran_node is None:
                raise WorkspaceError("manual placement requires core and RAN nodes")
            for label, value in (("core node", self.core_node), ("RAN node", self.ran_node)):
                assert value is not None
                if len(value) > 128 or any(
                    not (character.isalnum() or character in "._-")
                    for character in value
                ):
                    raise WorkspaceError(f"{label} contains unsafe characters")


@dataclass(frozen=True)
class ExperimentDesiredState:
    """Requested network state; provider-assigned runtime values are intentionally absent."""

    intent: str = "virtual-5g"
    core: CoreDesiredState = field(default_factory=CoreDesiredState)
    ran: RanDesiredState = field(default_factory=RanDesiredState)
    ue: UeDesiredState = field(default_factory=UeDesiredState)
    radio: RadioDesiredState = field(default_factory=RadioDesiredState)
    plmn: PlmnDesiredState = field(default_factory=PlmnDesiredState)
    dnns: tuple[DnnDesiredState, ...] = field(
        default_factory=lambda: (
            DnnDesiredState(name="internet", pdu_session_type="ipv4", ipv4_subnet="12.1.1.0/24"),
        )
    )
    slices: tuple[SliceDesiredState, ...] = field(
        default_factory=lambda: (SliceDesiredState(sst=1, dnn="internet"),)
    )
    multus: MultusDesiredState = field(default_factory=MultusDesiredState)
    ric: RicDesiredState = field(default_factory=RicDesiredState)
    placement: PlacementDesiredState = field(default_factory=PlacementDesiredState)

    def __post_init__(self) -> None:
        if self.intent not in {
            "virtual-5g",
            "physical-5g",
            "open-ran",
            "iot-to-5g",
            "custom",
        }:
            raise WorkspaceError("unsupported experiment intent")
        names = [dnn.name for dnn in self.dnns]
        if not names:
            raise WorkspaceError("experiment must configure at least one DNN")
        if len(names) != len(set(names)):
            raise WorkspaceError("DNN names must be unique")
        dnn_names = set(names)
        if not self.slices:
            raise WorkspaceError("experiment must configure at least one slice")
        slice_ids: set[tuple[int, str | None]] = set()
        for slice_spec in self.slices:
            if slice_spec.dnn not in dnn_names:
                raise WorkspaceError(
                    f"slice references unknown DNN '{slice_spec.dnn}'"
                )
            identifier = (slice_spec.sst, slice_spec.normalized_sd)
            if identifier in slice_ids:
                raise WorkspaceError("S-NSSAI values must be unique")
            slice_ids.add(identifier)
        if self.intent == "virtual-5g" and self.radio.mode == "physical":
            raise WorkspaceError("virtual-5g intent cannot require a physical radio")
        if self.intent == "physical-5g" and self.radio.mode == "virtual":
            raise WorkspaceError("physical-5g intent cannot require a virtual radio")
        if self.ran.architecture == "cu-du" and not self.ran.f1_enabled:
            raise WorkspaceError("CU/DU RAN requires F1")

    @classmethod
    def recommended(cls, *, intent: str = "virtual-5g") -> "ExperimentDesiredState":
        if intent == "physical-5g":
            radio = RadioDesiredState(mode="physical", backend="r2lab")
        elif intent == "virtual-5g":
            radio = RadioDesiredState(mode="virtual", backend="rfsim")
        else:
            radio = RadioDesiredState()
        return cls(intent=intent, radio=radio)

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "core": {
                "implementation": self.core.implementation,
                "namespace": self.core.namespace,
                "nrf_address_policy": self.core.nrf_address_policy,
                "nrf_address": self.core.nrf_address,
            },
            "ran": {
                "implementation": self.ran.implementation,
                "namespace": self.ran.namespace,
                "architecture": self.ran.architecture,
                "gnb_id": self.ran.gnb_id,
                "f1_enabled": self.ran.f1_enabled,
                "du_enabled": self.ran.du_enabled,
            },
            "ue": {
                "implementation": self.ue.implementation,
                "namespace": self.ue.namespace,
                "count": self.ue.count,
            },
            "radio": {
                "mode": self.radio.mode,
                "backend": self.radio.backend,
                "hardware": self.radio.hardware,
            },
            "plmn": {
                "mcc": self.plmn.mcc,
                "mnc": self.plmn.mnc,
                "tac": self.plmn.tac,
            },
            "dnns": [
                {
                    "name": item.name,
                    "pdu_session_type": item.pdu_session_type,
                    "ipv4_subnet": item.ipv4_subnet,
                    "ipv6_subnet": item.ipv6_subnet,
                }
                for item in self.dnns
            ],
            "slices": [
                {
                    "sst": item.sst,
                    "sd": item.normalized_sd,
                    "dnn": item.dnn,
                    "five_qi": item.five_qi,
                    "ambr_ul_bps": item.ambr_ul_bps,
                    "ambr_dl_bps": item.ambr_dl_bps,
                }
                for item in self.slices
            ],
            "multus": {
                "enabled": self.multus.enabled,
                "network": self.multus.network,
                "host_interface": self.multus.host_interface,
            },
            "ric": {
                "enabled": self.ric.enabled,
                "implementation": self.ric.implementation,
            },
            "placement": {
                "mode": self.placement.mode,
                "core_node": self.placement.core_node,
                "ran_node": self.placement.ran_node,
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ExperimentDesiredState":
        def section(name: str) -> Mapping[str, object]:
            raw = value.get(name, {})
            if not isinstance(raw, Mapping):
                raise WorkspaceError(f"experiment {name} section is malformed")
            return raw

        core = section("core")
        ran = section("ran")
        ue = section("ue")
        radio = section("radio")
        plmn = section("plmn")
        multus = section("multus")
        ric = section("ric")
        placement = section("placement")

        raw_dnns = value.get("dnns", [])
        raw_slices = value.get("slices", [])
        if not isinstance(raw_dnns, Sequence) or isinstance(raw_dnns, (str, bytes)):
            raise WorkspaceError("experiment DNN list is malformed")
        if not isinstance(raw_slices, Sequence) or isinstance(raw_slices, (str, bytes)):
            raise WorkspaceError("experiment slice list is malformed")

        def mapping_item(raw: object, label: str) -> Mapping[str, object]:
            if not isinstance(raw, Mapping):
                raise WorkspaceError(f"{label} entry is malformed")
            return raw

        return cls(
            intent=str(value.get("intent", "virtual-5g")),
            core=CoreDesiredState(
                implementation=str(core.get("implementation", "automatic")),
                namespace=str(core.get("namespace", "core")),
                nrf_address_policy=str(core.get("nrf_address_policy", "discover")),
                nrf_address=(str(core["nrf_address"]) if core.get("nrf_address") is not None else None),
            ),
            ran=RanDesiredState(
                implementation=str(ran.get("implementation", "automatic")),
                namespace=str(ran.get("namespace", "ran")),
                architecture=str(ran.get("architecture", "automatic")),
                gnb_id=int(ran.get("gnb_id", 0xE01)),
                f1_enabled=bool(ran.get("f1_enabled", False)),
                du_enabled=bool(ran.get("du_enabled", True)),
            ),
            ue=UeDesiredState(
                implementation=str(ue.get("implementation", "automatic")),
                namespace=str(ue.get("namespace", "ran")),
                count=int(ue.get("count", 1)),
            ),
            radio=RadioDesiredState(
                mode=str(radio.get("mode", "automatic")),
                backend=str(radio.get("backend", "automatic")),
                hardware=str(radio.get("hardware", "automatic")),
            ),
            plmn=PlmnDesiredState(
                mcc=str(plmn.get("mcc", "001")),
                mnc=str(plmn.get("mnc", "01")),
                tac=int(plmn.get("tac", 1)),
            ),
            dnns=tuple(
                DnnDesiredState(
                    name=str(mapping_item(raw, "DNN").get("name", "")),
                    pdu_session_type=str(mapping_item(raw, "DNN").get("pdu_session_type", "ipv4")),
                    ipv4_subnet=(str(mapping_item(raw, "DNN")["ipv4_subnet"]) if mapping_item(raw, "DNN").get("ipv4_subnet") is not None else None),
                    ipv6_subnet=(str(mapping_item(raw, "DNN")["ipv6_subnet"]) if mapping_item(raw, "DNN").get("ipv6_subnet") is not None else None),
                )
                for raw in raw_dnns
            ),
            slices=tuple(
                SliceDesiredState(
                    sst=int(mapping_item(raw, "slice").get("sst", 1)),
                    sd=(str(mapping_item(raw, "slice")["sd"]) if mapping_item(raw, "slice").get("sd") is not None else None),
                    dnn=str(mapping_item(raw, "slice").get("dnn", "")),
                    five_qi=int(mapping_item(raw, "slice").get("five_qi", 9)),
                    ambr_ul_bps=int(mapping_item(raw, "slice").get("ambr_ul_bps", 100_000_000)),
                    ambr_dl_bps=int(mapping_item(raw, "slice").get("ambr_dl_bps", 100_000_000)),
                )
                for raw in raw_slices
            ),
            multus=MultusDesiredState(
                enabled=bool(multus.get("enabled", False)),
                network=(str(multus["network"]) if multus.get("network") is not None else None),
                host_interface=(str(multus["host_interface"]) if multus.get("host_interface") is not None else None),
            ),
            ric=RicDesiredState(
                enabled=bool(ric.get("enabled", False)),
                implementation=str(ric.get("implementation", "flexric")),
            ),
            placement=PlacementDesiredState(
                mode=str(placement.get("mode", "automatic")),
                core_node=(str(placement["core_node"]) if placement.get("core_node") is not None else None),
                ran_node=(str(placement["ran_node"]) if placement.get("ran_node") is not None else None),
            ),
        )
