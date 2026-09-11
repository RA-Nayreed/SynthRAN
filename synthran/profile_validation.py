"""Strict validation for data-only 5G profile fields used by deployment templates."""
from __future__ import annotations

import ipaddress
import re
from typing import Any

_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_DNN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\Z"
)
_HEX_128 = re.compile(r"[0-9A-Fa-f]{32}\Z")
_BANDWIDTH = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:bps|Kbps|Mbps|Gbps)\Z")


def _mapping(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _exact_keys(value: dict, allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _integer_text(value: Any, label: str, minimum: int, maximum: int) -> str:
    text = str(value)
    if not re.fullmatch(r"[0-9]+", text):
        raise ValueError(f"{label} must be decimal digits")
    number = int(text)
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return text


def _safe_name(value: Any, label: str) -> str:
    text = str(value)
    if not _SAFE_NAME.fullmatch(text):
        raise ValueError(f"{label} contains unsupported characters")
    return text


def _validate_transport(entry: dict, label: str) -> None:
    mode = str(entry.get("mode", "mbim")).lower()
    if mode not in {"mbim", "qmi"}:
        raise ValueError(f"{label}.mode must be mbim or qmi")
    interface = entry.get("interface", "wwan0")
    if interface != "wwan0":
        raise ValueError(f"{label}.interface must be wwan0 for the supported physical workflow")
    if "mbim_session" in entry:
        try:
            session = int(entry["mbim_session"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label}.mbim_session must be an integer") from error
        if mode != "mbim" or session != 0:
            raise ValueError(f"{label}.mbim_session is supported only as session 0 in mbim mode")


def validate_profile(profile: Any) -> None:
    """Reject malformed or shell-active telecom profile values before rendering."""
    profile = _mapping(profile, "5G profile")
    _exact_keys(profile, {"plmn", "dnns", "slices", "security", "ues"}, "5G profile")

    plmn = _mapping(profile.get("plmn"), "plmn")
    _exact_keys(plmn, {"mcc", "mnc", "tac"}, "plmn")
    if not re.fullmatch(r"[0-9]{3}", str(plmn.get("mcc", ""))):
        raise ValueError("plmn.mcc must contain exactly 3 digits")
    if not re.fullmatch(r"[0-9]{2,3}", str(plmn.get("mnc", ""))):
        raise ValueError("plmn.mnc must contain 2 or 3 digits")
    _integer_text(plmn.get("tac"), "plmn.tac", 0, 16_777_215)

    dnns = profile.get("dnns")
    if not isinstance(dnns, list) or not dnns:
        raise ValueError("dnns must be a non-empty list")
    dnn_names: list[str] = []
    for index, raw in enumerate(dnns):
        entry = _mapping(raw, f"dnns[{index}]")
        _exact_keys(entry, {"name", "pdu_type"}, f"dnns[{index}]")
        name = str(entry.get("name", ""))
        if len(name) > 100 or not _DNN.fullmatch(name):
            raise ValueError(f"dnns[{index}].name is not a supported DNN")
        if entry.get("pdu_type") not in {"IPV4", "IPV6", "IPV4V6"}:
            raise ValueError(f"dnns[{index}].pdu_type is unsupported")
        dnn_names.append(name)
    if len(dnn_names) != len(set(dnn_names)):
        raise ValueError("DNN names must be unique")

    slices = profile.get("slices")
    if not isinstance(slices, list) or not slices:
        raise ValueError("slices must be a non-empty list")
    slice_names: list[str] = []
    for index, raw in enumerate(slices):
        label = f"slices[{index}]"
        entry = _mapping(raw, label)
        _exact_keys(entry, {"name", "dnn", "sst", "sd", "qos", "bandwidth", "ip_prefix"}, label)
        name = _safe_name(entry.get("name", ""), f"{label}.name")
        slice_names.append(name)
        if entry.get("dnn") not in dnn_names:
            raise ValueError(f"{label}.dnn references an unknown DNN")
        _integer_text(entry.get("sst"), f"{label}.sst", 0, 255)
        sd = str(entry.get("sd", ""))
        if sd != "EMPTY" and not re.fullmatch(r"[0-9A-Fa-f]{6}", sd):
            raise ValueError(f"{label}.sd must be EMPTY or exactly 6 hexadecimal digits")

        qos = _mapping(entry.get("qos"), f"{label}.qos")
        _exact_keys(qos, {"five_qi", "arp", "priority_level"}, f"{label}.qos")
        _integer_text(qos.get("five_qi"), f"{label}.qos.five_qi", 1, 255)
        _integer_text(qos.get("priority_level"), f"{label}.qos.priority_level", 1, 127)
        arp = _mapping(qos.get("arp"), f"{label}.qos.arp")
        _exact_keys(arp, {"priority_level", "preempt_cap", "preempt_vuln"}, f"{label}.qos.arp")
        _integer_text(arp.get("priority_level"), f"{label}.qos.arp.priority_level", 1, 15)
        if arp.get("preempt_cap") not in {"MAY_PREEMPT", "NOT_PREEMPT"}:
            raise ValueError(f"{label}.qos.arp.preempt_cap is unsupported")
        if arp.get("preempt_vuln") not in {"PREEMPTABLE", "NOT_PREEMPTABLE"}:
            raise ValueError(f"{label}.qos.arp.preempt_vuln is unsupported")

        bandwidth = _mapping(entry.get("bandwidth"), f"{label}.bandwidth")
        _exact_keys(bandwidth, {"uplink", "downlink"}, f"{label}.bandwidth")
        for direction in ("uplink", "downlink"):
            if not _BANDWIDTH.fullmatch(str(bandwidth.get(direction, ""))):
                raise ValueError(f"{label}.bandwidth.{direction} has an unsupported format")

        prefix = str(entry.get("ip_prefix", ""))
        try:
            network = ipaddress.ip_network(prefix + ".0/24", strict=True)
        except ValueError as error:
            raise ValueError(f"{label}.ip_prefix must contain exactly three IPv4 octets") from error
        if not isinstance(network, ipaddress.IPv4Network):
            raise ValueError(f"{label}.ip_prefix must be IPv4")
    if len(slice_names) != len(set(slice_names)):
        raise ValueError("slice names must be unique")

    security = _mapping(profile.get("security"), "security")
    _exact_keys(security, {"full_key", "opc"}, "security")
    for key in ("full_key", "opc"):
        if not _HEX_128.fullmatch(str(security.get(key, ""))):
            raise ValueError(f"security.{key} must be exactly 32 hexadecimal digits")

    ues = _mapping(profile.get("ues"), "ues")
    if not ues:
        raise ValueError("ues must define at least one UE")
    for name, raw in ues.items():
        _safe_name(name, "UE name")
        label = f"ues.{name}"
        entry = _mapping(raw, label)
        _exact_keys(entry, {"imsi_suffix", "slice", "mode", "interface", "mbim_session"}, label)
        if not re.fullmatch(r"[0-9]{10}", str(entry.get("imsi_suffix", ""))):
            raise ValueError(f"{label}.imsi_suffix must contain exactly 10 digits")
        if entry.get("slice") not in slice_names:
            raise ValueError(f"{label}.slice references an unknown slice")
        _validate_transport(entry, label)


def validate_ue_profile_overrides(overrides: Any, profile: dict) -> None:
    if overrides is None:
        return
    overrides = _mapping(overrides, "deployment.ue_profiles")
    slice_names = {entry["name"] for entry in profile["slices"]}
    base_ues = profile.get("ues", {})
    for name, raw in overrides.items():
        _safe_name(name, "deployment.ue_profiles UE name")
        label = f"deployment.ue_profiles.{name}"
        entry = _mapping(raw, label)
        _exact_keys(entry, {"imsi_suffix", "slice", "mode", "interface", "mbim_session"}, label)
        if "imsi_suffix" in entry and not re.fullmatch(r"[0-9]{10}", str(entry["imsi_suffix"])):
            raise ValueError(f"{label}.imsi_suffix must contain exactly 10 digits")
        if "slice" in entry and entry["slice"] not in slice_names:
            raise ValueError(f"{label}.slice references an unknown slice")
        effective = dict(base_ues.get(name, {}))
        effective.update(entry)
        _validate_transport(effective, label)
