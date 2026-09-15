"""Read-only transport/RAN telemetry for Experiment 2.

The experiment never reconfigures the accepted deployment.  These helpers reuse
its exact SSH inventory and collect bounded host/network/Kubernetes evidence so
an end-to-end timing result can later be interpreted against infrastructure
state instead of being attributed to the RAN by assumption.
"""
from __future__ import annotations

import json
import time
from typing import Any

from .traffic import _ssh, _transport_value

_RELEVANT_POD_TOKENS = ("gnb", "srsran", "amf", "smf", "upf", "spgwu")
_RELEVANT_PROCESS_TOKENS = ("gnb", "srsran", "nr-softmodem", "amf", "smf", "upf", "spgwu")
_SELECTED_NET_COUNTERS = {
    "Ip": ("InReceives", "InDiscards", "OutRequests", "OutDiscards"),
    "Tcp": ("ActiveOpens", "PassiveOpens", "InSegs", "OutSegs", "RetransSegs"),
    "Udp": ("InDatagrams", "NoPorts", "InErrors", "OutDatagrams", "RcvbufErrors", "SndbufErrors"),
    "TcpExt": ("TCPSynRetrans", "TCPTimeouts", "TCPFastRetrans", "TCPLostRetransmit"),
}


def _command(environment: dict[str, Any], host: str, remote: str) -> dict[str, Any]:
    try:
        process = _ssh(environment, host, remote, capture=True, check=False)
    except Exception as exc:  # evidence collection must not mutate or mask the experiment
        return {"available": False, "returncode": None, "stdout": "", "stderr": str(exc)}
    return {
        "available": process.returncode == 0,
        "returncode": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
    }


def _json_output(result: dict[str, Any]) -> Any | None:
    if not result.get("available"):
        return None
    try:
        return json.loads(str(result.get("stdout", "")))
    except json.JSONDecodeError:
        return None


def _parse_proc_net(text: str) -> dict[str, dict[str, int]]:
    lines = [line.strip() for line in text.splitlines() if ":" in line]
    parsed: dict[str, dict[str, int]] = {}
    index = 0
    while index + 1 < len(lines):
        header, values = lines[index], lines[index + 1]
        h_name, _, h_fields = header.partition(":")
        v_name, _, v_fields = values.partition(":")
        if h_name != v_name:
            index += 1
            continue
        names = h_fields.split()
        raw_values = v_fields.split()
        if len(names) == len(raw_values):
            row: dict[str, int] = {}
            for name, value in zip(names, raw_values):
                try:
                    row[name] = int(value)
                except ValueError:
                    continue
            parsed[h_name] = row
        index += 2
    return parsed


def _selected_network_counters(text: str) -> dict[str, dict[str, int]]:
    parsed = _parse_proc_net(text)
    return {
        section: {
            key: parsed.get(section, {}).get(key)
            for key in keys
            if key in parsed.get(section, {})
        }
        for section, keys in _SELECTED_NET_COUNTERS.items()
        if section in parsed
    }


def _pod_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"available": False, "pods": []}
    rows = []
    for item in payload.get("items", []):
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        status = item.get("status", {}) if isinstance(item, dict) else {}
        spec = item.get("spec", {}) if isinstance(item, dict) else {}
        name = str(metadata.get("name", ""))
        if not any(token in name.lower() for token in _RELEVANT_POD_TOKENS):
            continue
        container_statuses = status.get("containerStatuses", []) or []
        rows.append(
            {
                "namespace": metadata.get("namespace"),
                "name": name,
                "uid": metadata.get("uid"),
                "node": spec.get("nodeName"),
                "phase": status.get("phase"),
                "pod_ip": status.get("podIP"),
                "host_ip": status.get("hostIP"),
                "start_time": status.get("startTime"),
                "containers": [
                    {
                        "name": row.get("name"),
                        "ready": row.get("ready"),
                        "restart_count": row.get("restartCount"),
                        "image_id": row.get("imageID"),
                    }
                    for row in container_statuses
                    if isinstance(row, dict)
                ],
            }
        )
    return {"available": True, "pods": rows}


def _interface_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list):
        return {"available": False, "interfaces": []}
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "ifname": item.get("ifname"),
                "operstate": item.get("operstate"),
                "mtu": item.get("mtu"),
                "address": item.get("address"),
                "stats64": item.get("stats64") or item.get("stats"),
            }
        )
    return {"available": True, "interfaces": rows}


def _relevant_processes(text: str) -> list[str]:
    result = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(token in lowered for token in _RELEVANT_PROCESS_TOKENS):
            result.append(line.strip())
    return result[:100]


def _host_snapshot(environment: dict[str, Any], host: str, roles: list[str]) -> dict[str, Any]:
    clock = _command(
        environment,
        host,
        "printf '%s\\n' \"$(date -u --iso-8601=ns 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)\"; "
        "timedatectl show -p NTPSynchronized --value 2>/dev/null || true",
    )
    load = _command(environment, host, "cat /proc/uptime; cat /proc/loadavg")
    links = _command(environment, host, "ip -s -j link 2>/dev/null")
    qdisc = _command(environment, host, "tc -s -j qdisc show 2>/dev/null")
    proc_net = _command(environment, host, "cat /proc/net/snmp /proc/net/netstat 2>/dev/null")
    processes = _command(environment, host, "ps -eo pid=,etimes=,comm= 2>/dev/null")
    pods = _command(environment, host, "kubectl get pods -A -o json 2>/dev/null")

    clock_lines = [line.strip() for line in str(clock.get("stdout", "")).splitlines() if line.strip()]
    load_lines = [line.strip() for line in str(load.get("stdout", "")).splitlines() if line.strip()]
    qdisc_payload = _json_output(qdisc)
    return {
        "host": host,
        "roles": roles,
        "clock": {
            "available": clock.get("returncode") is not None,
            "remote_utc": clock_lines[0] if clock_lines else None,
            "ntp_synchronized": (
                clock_lines[1].lower() == "yes" if len(clock_lines) > 1 else None
            ),
        },
        "uptime_seconds": (
            float(load_lines[0].split()[0]) if load_lines and load_lines[0].split() else None
        ),
        "loadavg": load_lines[1].split()[:3] if len(load_lines) > 1 else [],
        "interfaces": _interface_summary(_json_output(links)),
        "qdisc": {
            "available": isinstance(qdisc_payload, list),
            "entries": qdisc_payload if isinstance(qdisc_payload, list) else [],
        },
        "network_counters": _selected_network_counters(str(proc_net.get("stdout", ""))),
        "relevant_processes": _relevant_processes(str(processes.get("stdout", ""))),
        "kubernetes": _pod_summary(_json_output(pods)),
    }


def _binding_summary(binding: dict[str, Any], role: str) -> dict[str, Any]:
    return {
        "role": role,
        "device": binding.get("device"),
        "index": binding.get("index"),
        "imsi": binding.get("imsi"),
        "slice": binding.get("slice"),
        "dnn": binding.get("dnn"),
        "address": binding.get("address"),
        "interface": _transport_value(binding, "interface"),
        "host": _transport_value(binding, "host"),
    }


def capture_transport_snapshot(
    environment: dict[str, Any],
    *,
    broker_address: str | None = None,
) -> dict[str, Any]:
    """Capture bounded, read-only evidence from every experiment-relevant host."""
    deployment = environment["deployment"]
    bindings = list(environment.get("bindings", []))
    workload = bindings[0] if len(bindings) > 0 else {}
    competitor = bindings[1] if len(bindings) > 1 else {}

    roles_by_host: dict[str, list[str]] = {}
    for role in ("ran", "core", "broker"):
        host = str(deployment.get("nodes", {}).get(role) or "")
        if host:
            roles_by_host.setdefault(host, []).append(role)
    if deployment.get("platform") == "r2lab":
        for role, binding in (("workload_ue", workload), ("competing_ue", competitor)):
            host = str(_transport_value(binding, "host") or binding.get("device") or "")
            if host:
                roles_by_host.setdefault(host, []).append(role)

    hosts = {
        host: _host_snapshot(environment, host, roles)
        for host, roles in roles_by_host.items()
    }
    return {
        "schema_version": 1,
        "captured_epoch_s": time.time(),
        "read_only": True,
        "deployment_hash": environment.get("deployment_hash"),
        "platform": deployment.get("platform"),
        "core": deployment.get("core"),
        "ran": deployment.get("ran"),
        "radio_unit": deployment.get("radio_unit"),
        "broker_address": broker_address,
        "bindings": [
            _binding_summary(workload, "workload_ue"),
            _binding_summary(competitor, "competing_ue"),
        ],
        "hosts": hosts,
        "interpretation": (
            "Read-only diagnostic evidence. Host/interface/pod counter changes can support "
            "bottleneck diagnosis but do not by themselves prove radio-scheduler causality."
        ),
    }
