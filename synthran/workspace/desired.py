"""Validated desired configuration for one SynthRAN 5G/Open RAN experiment."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import ipaddress
import re

from synthran.workspace.model import WorkspaceError


NAMESPACE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
DNN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,61}[a-z0-9])?$")
HEX_SD_RE = re.compile(r"^[0-9A-Fa-f]{6}$")
RESOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
INTERFACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

CORE_IMPLEMENTATIONS = frozenset({"automatic", "open5gs", "oai", "free5gc"})
RAN_IMPLEMENTATIONS = frozenset({"automatic", "srsran", "oai", "ueransim"})
UE_IMPLEMENTATIONS = frozenset({"automatic", "srsue", "oai", "ueransim"})
RADIO_MODES = frozenset({"automatic", "virtual", "physical"})
RADIO_BACKENDS = frozenset({"automatic", "rfsim", "r2lab"})
RADIO_HARDWARE = frozenset({"automatic", "n300", "n320"})
RAN_ARCHITECTURES = frozenset(
    {"automatic", "monolithic", "cu-du", "cu-cp-up-du"}
)
PDU_SESSION_TYPES = frozenset({"ipv4", "ipv6", "ipv4v6"})
ADDRESS_POLICIES = frozenset({"discover", "static"})
PLACEMENT_MODES = frozenset({"automatic", "manual"})
EXPERIMENT_INTENTS = frozenset(
    {"unspecified", "virtual-5g", "physical-5g", "open-ran", "iot-to-5g"}
)


def _validate_namespace(value: str, label: str) -> str:
    if NAMESPACE_RE.fullmatch(value) is None:
        raise WorkspaceError(f"{label} must be a valid Kubernetes namespace name")
    return value


def _validate_dnn_name(value: str) -> str:
    if DNN_RE.fullmatch(value) is None:
        raise WorkspaceError("DNN name contains unsupported characters")
    return value


def _validate_plmn(mcc: str, mnc: str, label: str = "PLMN") -> None:
    if len(mcc) != 3 or not mcc.isdigit():
        raise WorkspaceError(f"{label} MCC must contain exactly three digits")
    if len(mnc) not in {2, 3} or not mnc.isdigit():
        raise WorkspaceError(f"{label} MNC must contain two or three digits")


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


def _section(value: Mapping[str, object], name: str) -> Mapping[str, object]:
    raw = value.get(name, {})
    if not isinstance(raw, Mapping):
        raise WorkspaceError(f"experiment {name} section is malformed")
    return raw


def _sequence(value: Mapping[str, object], name: str) -> Sequence[object]:
    raw = value.get(name, [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise WorkspaceError(f"experiment {name} list is malformed")
    return raw


def _mapping_item(raw: object, label: str) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise WorkspaceError(f"{label} entry is malformed")
    return raw


def _string(
    value: Mapping[str, object],
    key: str,
    default: str,
    label: str,
) -> str:
    raw = value.get(key, default)
    if not isinstance(raw, str):
        raise WorkspaceError(f"{label} must be text")
    return raw


def _optional_string(
    value: Mapping[str, object], key: str, label: str
) -> str | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise WorkspaceError(f"{label} must be text or null")
    return raw


def _boolean(
    value: Mapping[str, object],
    key: str,
    default: bool,
    label: str,
) -> bool:
    raw = value.get(key, default)
    if type(raw) is not bool:
        raise WorkspaceError(f"{label} must be true or false")
    return raw


def _integer(
    value: Mapping[str, object],
    key: str,
    default: int,
    label: str,
) -> int:
    raw = value.get(key, default)
    if type(raw) is not int:
        raise WorkspaceError(f"{label} must be an integer")
    return raw


@dataclass(frozen=True)
class CoreDesiredState:
    enabled: bool = True
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
    enabled: bool = True
    implementation: str = "automatic"
    namespace: str = "ran"
    architecture: str = "automatic"
    gnb_id: int = 0xE01
    f1_enabled: bool = False
    e1_enabled: bool = False
    du_enabled: bool = True

    def __post_init__(self) -> None:
        if self.implementation not in RAN_IMPLEMENTATIONS:
            raise WorkspaceError("unsupported RAN implementation")
        _validate_namespace(self.namespace, "RAN namespace")
        if self.architecture not in RAN_ARCHITECTURES:
            raise WorkspaceError("unsupported RAN architecture")
        if self.gnb_id < 0 or self.gnb_id > 0xFFFFFFFF:
            raise WorkspaceError("gNB ID must be between 0 and 0xffffffff")
        if self.architecture == "monolithic" and (
            self.f1_enabled or self.e1_enabled
        ):
            raise WorkspaceError("monolithic RAN cannot request F1 or E1")
        if self.architecture in {"cu-du", "cu-cp-up-du"} and not self.du_enabled:
            raise WorkspaceError("split RAN requires a DU")
        if self.architecture in {"cu-du", "cu-cp-up-du"} and not self.f1_enabled:
            raise WorkspaceError("CU/DU RAN requires F1")
        if self.architecture == "cu-cp-up-du" and not self.e1_enabled:
            raise WorkspaceError("CU-CP/CU-UP split requires E1")


@dataclass(frozen=True)
class UeDesiredState:
    enabled: bool = True
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
        _validate_plmn(self.mcc, self.mnc)
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
    plmn_mcc: str | None = None
    plmn_mnc: str | None = None

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
        if (self.plmn_mcc is None) != (self.plmn_mnc is None):
            raise WorkspaceError("slice PLMN override requires both MCC and MNC")
        if self.plmn_mcc is not None and self.plmn_mnc is not None:
            _validate_plmn(self.plmn_mcc, self.plmn_mnc, "slice PLMN")

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
            if self.host_interface is not None and INTERFACE_RE.fullmatch(
                self.host_interface
            ) is None:
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
    deployment_node: str | None = None
    core_node: str | None = None
    ran_node: str | None = None
    extra_resources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in PLACEMENT_MODES:
            raise WorkspaceError("placement mode must be automatic or manual")
        pinned = (self.deployment_node, self.core_node, self.ran_node)
        if self.mode == "automatic" and (
            any(item is not None for item in pinned) or self.extra_resources
        ):
            raise WorkspaceError("automatic placement cannot pin resources")
        if self.mode == "manual":
            if self.core_node is None or self.ran_node is None:
                raise WorkspaceError("manual placement requires core and RAN nodes")
            for label, value in (
                ("deployment node", self.deployment_node),
                ("core node", self.core_node),
                ("RAN node", self.ran_node),
            ):
                if value is not None and RESOURCE_RE.fullmatch(value) is None:
                    raise WorkspaceError(f"{label} contains unsafe characters")
            if len(set(self.extra_resources)) != len(self.extra_resources):
                raise WorkspaceError("extra resource names must be unique")
            for resource in self.extra_resources:
                if RESOURCE_RE.fullmatch(resource) is None:
                    raise WorkspaceError("extra resource name contains unsafe characters")


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
            DnnDesiredState(
                name="internet",
                pdu_session_type="ipv4",
                ipv4_subnet="12.1.1.0/24",
            ),
        )
    )
    slices: tuple[SliceDesiredState, ...] = field(
        default_factory=lambda: (SliceDesiredState(sst=1, dnn="internet"),)
    )
    multus: MultusDesiredState = field(default_factory=MultusDesiredState)
    ric: RicDesiredState = field(default_factory=RicDesiredState)
    placement: PlacementDesiredState = field(default_factory=PlacementDesiredState)

    def __post_init__(self) -> None:
        if self.intent not in EXPERIMENT_INTENTS:
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
        if not self.core.enabled and not self.ran.enabled:
            raise WorkspaceError("experiment must enable the core or RAN")

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
                "enabled": self.core.enabled,
                "implementation": self.core.implementation,
                "namespace": self.core.namespace,
                "nrf_address_policy": self.core.nrf_address_policy,
                "nrf_address": self.core.nrf_address,
            },
            "ran": {
                "enabled": self.ran.enabled,
                "implementation": self.ran.implementation,
                "namespace": self.ran.namespace,
                "architecture": self.ran.architecture,
                "gnb_id": self.ran.gnb_id,
                "f1_enabled": self.ran.f1_enabled,
                "e1_enabled": self.ran.e1_enabled,
                "du_enabled": self.ran.du_enabled,
            },
            "ue": {
                "enabled": self.ue.enabled,
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
                    "plmn_mcc": item.plmn_mcc,
                    "plmn_mnc": item.plmn_mnc,
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
                "deployment_node": self.placement.deployment_node,
                "core_node": self.placement.core_node,
                "ran_node": self.placement.ran_node,
                "extra_resources": list(self.placement.extra_resources),
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ExperimentDesiredState":
        intent = _string(value, "intent", "virtual-5g", "experiment intent")
        core = _section(value, "core")
        ran = _section(value, "ran")
        ue = _section(value, "ue")
        radio = _section(value, "radio")
        plmn = _section(value, "plmn")
        multus = _section(value, "multus")
        ric = _section(value, "ric")
        placement = _section(value, "placement")

        dnns: list[DnnDesiredState] = []
        for raw in _sequence(value, "dnns"):
            item = _mapping_item(raw, "DNN")
            dnns.append(
                DnnDesiredState(
                    name=_string(item, "name", "", "DNN name"),
                    pdu_session_type=_string(
                        item,
                        "pdu_session_type",
                        "ipv4",
                        "DNN PDU session type",
                    ),
                    ipv4_subnet=_optional_string(
                        item, "ipv4_subnet", "DNN IPv4 subnet"
                    ),
                    ipv6_subnet=_optional_string(
                        item, "ipv6_subnet", "DNN IPv6 subnet"
                    ),
                )
            )

        slices: list[SliceDesiredState] = []
        for raw in _sequence(value, "slices"):
            item = _mapping_item(raw, "slice")
            slices.append(
                SliceDesiredState(
                    sst=_integer(item, "sst", 1, "slice SST"),
                    sd=_optional_string(item, "sd", "slice SD"),
                    dnn=_string(item, "dnn", "", "slice DNN"),
                    five_qi=_integer(item, "five_qi", 9, "slice 5QI"),
                    ambr_ul_bps=_integer(
                        item,
                        "ambr_ul_bps",
                        100_000_000,
                        "slice uplink AMBR",
                    ),
                    ambr_dl_bps=_integer(
                        item,
                        "ambr_dl_bps",
                        100_000_000,
                        "slice downlink AMBR",
                    ),
                    plmn_mcc=_optional_string(item, "plmn_mcc", "slice MCC"),
                    plmn_mnc=_optional_string(item, "plmn_mnc", "slice MNC"),
                )
            )

        raw_extra = placement.get("extra_resources", [])
        if not isinstance(raw_extra, Sequence) or isinstance(raw_extra, (str, bytes)):
            raise WorkspaceError("extra resource list is malformed")
        extras: list[str] = []
        for raw in raw_extra:
            if not isinstance(raw, str):
                raise WorkspaceError("extra resource name must be text")
            extras.append(raw)

        return cls(
            intent=intent,
            core=CoreDesiredState(
                enabled=_boolean(core, "enabled", True, "core enabled"),
                implementation=_string(
                    core,
                    "implementation",
                    "automatic",
                    "core implementation",
                ),
                namespace=_string(core, "namespace", "core", "core namespace"),
                nrf_address_policy=_string(
                    core,
                    "nrf_address_policy",
                    "discover",
                    "NRF address policy",
                ),
                nrf_address=_optional_string(core, "nrf_address", "NRF address"),
            ),
            ran=RanDesiredState(
                enabled=_boolean(ran, "enabled", True, "RAN enabled"),
                implementation=_string(
                    ran,
                    "implementation",
                    "automatic",
                    "RAN implementation",
                ),
                namespace=_string(ran, "namespace", "ran", "RAN namespace"),
                architecture=_string(
                    ran,
                    "architecture",
                    "automatic",
                    "RAN architecture",
                ),
                gnb_id=_integer(ran, "gnb_id", 0xE01, "gNB ID"),
                f1_enabled=_boolean(ran, "f1_enabled", False, "F1 enabled"),
                e1_enabled=_boolean(ran, "e1_enabled", False, "E1 enabled"),
                du_enabled=_boolean(ran, "du_enabled", True, "DU enabled"),
            ),
            ue=UeDesiredState(
                enabled=_boolean(ue, "enabled", True, "UE enabled"),
                implementation=_string(
                    ue,
                    "implementation",
                    "automatic",
                    "UE implementation",
                ),
                namespace=_string(ue, "namespace", "ran", "UE namespace"),
                count=_integer(ue, "count", 1, "UE count"),
            ),
            radio=RadioDesiredState(
                mode=_string(radio, "mode", "automatic", "radio mode"),
                backend=_string(
                    radio,
                    "backend",
                    "automatic",
                    "radio backend",
                ),
                hardware=_string(
                    radio,
                    "hardware",
                    "automatic",
                    "radio hardware",
                ),
            ),
            plmn=PlmnDesiredState(
                mcc=_string(plmn, "mcc", "001", "MCC"),
                mnc=_string(plmn, "mnc", "01", "MNC"),
                tac=_integer(plmn, "tac", 1, "TAC"),
            ),
            dnns=tuple(dnns),
            slices=tuple(slices),
            multus=MultusDesiredState(
                enabled=_boolean(multus, "enabled", False, "Multus enabled"),
                network=_optional_string(multus, "network", "Multus network"),
                host_interface=_optional_string(
                    multus,
                    "host_interface",
                    "Multus host interface",
                ),
            ),
            ric=RicDesiredState(
                enabled=_boolean(ric, "enabled", False, "RIC enabled"),
                implementation=_string(
                    ric,
                    "implementation",
                    "flexric",
                    "RIC implementation",
                ),
            ),
            placement=PlacementDesiredState(
                mode=_string(
                    placement,
                    "mode",
                    "automatic",
                    "placement mode",
                ),
                deployment_node=_optional_string(
                    placement,
                    "deployment_node",
                    "deployment node",
                ),
                core_node=_optional_string(
                    placement,
                    "core_node",
                    "core node",
                ),
                ran_node=_optional_string(
                    placement,
                    "ran_node",
                    "RAN node",
                ),
                extra_resources=tuple(extras),
            ),
        )
