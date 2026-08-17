"""UE-path instrumentation helpers for controlled research experiments."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import json
import math
from pathlib import Path
import re
import shlex
from typing import Any, Callable, Iterator, Mapping

from synthran.experiment import build_scenario as build_base_scenario
from synthran.experiment import runtime as base_runtime
from synthran.fiveg_ansible import NetworkInventory
from synthran.live_preflight import ssh_command
from synthran.research import (
    LOAD_RESULT_SCHEMA,
    PROBE_SCHEMA,
    ResearchError,
    ResearchExperimentSpec,
    append_jsonl,
)


DEFAULT_RESEARCH_RUN_ROOT = Path(".synthran/experiments")
_PING_TIME_RE = re.compile(r"time[=<]([0-9]+(?:\.[0-9]+)?)\s*ms")
_PING_SEQ_RE = re.compile(r"icmp_seq[= ]([0-9]+)")
_PING_EPOCH_RE = re.compile(r"^\[([0-9]+(?:\.[0-9]+)?)\]")


@dataclass(frozen=True)
class ResearchRunResult:
    run_id: str
    run_directory: Path
    summary_path: Path
    ready_for_campaign_analysis: bool
    path_acceptance_ready: bool


def _kubectl_exec_command(
    inventory: NetworkInventory,
    ue_pod: str,
    *command: str,
) -> tuple[str, ...]:
    return tuple(
        ssh_command(
            inventory.core_node,
            "sh",
            "-c",
            "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
            f"-n {base_runtime.KUBERNETES_NAMESPACE} {shlex.quote(ue_pod)} -c ue -- "
            + " ".join(shlex.quote(part) for part in command),
        )
    )


def _check_research_tools(
    inventory: NetworkInventory,
    ue_pod: str,
    *,
    load_enabled: bool,
) -> None:
    ue_tools = ["ip", "ping"]
    if load_enabled:
        ue_tools.append("iperf3")
    script = (
        "for x in "
        + " ".join(ue_tools)
        + '; do command -v "$x" >/dev/null || exit 7; done'
    )
    result = base_runtime._run(
        _kubectl_exec_command(inventory, ue_pod, "sh", "-c", script),
        timeout_seconds=15,
    )
    if result.returncode != 0:
        raise ResearchError("UE container is missing required research measurement tools")
    if load_enabled:
        base_runtime._remote(
            inventory,
            "sh",
            "-c",
            "command -v iperf3 >/dev/null",
            label="research load server tool probe",
            timeout_seconds=10,
        )


def _target_prefix(target: str) -> str:
    try:
        address = ipaddress.ip_address(target)
    except ValueError as exc:
        raise ResearchError("research target must be a literal IPv4 address") from exc
    if not isinstance(address, ipaddress.IPv4Address):
        raise ResearchError("research target must be a literal IPv4 address")
    return f"{address}/32"


def _target_route_uses_tunnel(
    inventory: NetworkInventory,
    ue_pod: str,
    *,
    pdu_address: str,
    target: str,
) -> bool:
    result = base_runtime._run(
        _kubectl_exec_command(
            inventory,
            ue_pod,
            "ip",
            "route",
            "get",
            target,
            "from",
            pdu_address,
        ),
        timeout_seconds=10,
    )
    if result.returncode != 0:
        raise ResearchError("research target route could not be inspected")
    return "dev tun_srsue1" in result.stdout


def _prove_target_route(
    inventory: NetworkInventory,
    ue_pod: str,
    *,
    pdu_address: str,
    target: str,
) -> None:
    if not _target_route_uses_tunnel(
        inventory,
        ue_pod,
        pdu_address=pdu_address,
        target=target,
    ):
        raise ResearchError("research target route is not proven through tun_srsue1")


def _remove_target_route(
    inventory: NetworkInventory,
    ue_pod: str,
    *,
    pdu_address: str,
    target: str,
) -> None:
    prefix = _target_prefix(target)
    result = base_runtime._run(
        _kubectl_exec_command(
            inventory,
            ue_pod,
            "ip",
            "route",
            "del",
            prefix,
            "dev",
            "tun_srsue1",
        ),
        timeout_seconds=10,
    )
    if result.returncode != 0:
        raise ResearchError("owned research target route cleanup failed")
    if _target_route_uses_tunnel(
        inventory,
        ue_pod,
        pdu_address=pdu_address,
        target=target,
    ):
        raise ResearchError("owned research target route remained after cleanup")


def _install_target_route(
    inventory: NetworkInventory,
    ue_pod: str,
    *,
    pdu_address: str,
    target: str,
) -> bool:
    prefix = _target_prefix(target)
    if _target_route_uses_tunnel(
        inventory,
        ue_pod,
        pdu_address=pdu_address,
        target=target,
    ):
        return False

    result = base_runtime._run(
        _kubectl_exec_command(
            inventory,
            ue_pod,
            "ip",
            "route",
            "add",
            prefix,
            "dev",
            "tun_srsue1",
        ),
        timeout_seconds=10,
    )
    if result.returncode != 0:
        raise ResearchError(
            "unable to install exact research target route without replacing existing state"
        )
    try:
        _prove_target_route(
            inventory,
            ue_pod,
            pdu_address=pdu_address,
            target=target,
        )
    except Exception as exc:
        try:
            _remove_target_route(
                inventory,
                ue_pod,
                pdu_address=pdu_address,
                target=target,
            )
        except Exception as cleanup_exc:
            raise ResearchError(
                "research target route proof failed and route cleanup failed closed: "
                f"{exc}; {cleanup_exc}"
            ) from exc
        raise
    return True


def _start_probe(
    *,
    inventory: NetworkInventory,
    ue_pod: str,
    target: str,
    duration_seconds: int,
    interval_seconds: float,
    repository_root: Path,
    log_path: Path,
) -> base_runtime.ManagedProcess:
    command = _kubectl_exec_command(
        inventory,
        ue_pod,
        "ping",
        "-n",
        "-D",
        "-I",
        "tun_srsue1",
        "-i",
        f"{interval_seconds:.3f}",
        "-w",
        str(duration_seconds),
        target,
    )
    return base_runtime._start_process(
        "research RTT probe",
        command,
        cwd=repository_root,
        log_path=log_path,
    )


def _parse_probe_log(
    path: Path,
    destination: Path,
    *,
    interval_seconds: float,
    window_started_at_utc: datetime | None = None,
    window_ended_at_utc: datetime | None = None,
) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise ResearchError("unable to read RTT probe log") from exc
    seen: dict[int, tuple[float, float | None]] = {}
    for line in lines:
        seq_match = _PING_SEQ_RE.search(line)
        time_match = _PING_TIME_RE.search(line)
        if seq_match is None or time_match is None:
            continue
        epoch_match = _PING_EPOCH_RE.search(line)
        seen[int(seq_match.group(1))] = (
            float(time_match.group(1)),
            float(epoch_match.group(1)) if epoch_match is not None else None,
        )
    if not seen:
        raise ResearchError("RTT probe produced no successful samples")

    first_seen = min(seen)
    anchor_epoch = seen[first_seen][1]
    if (window_started_at_utc is not None or window_ended_at_utc is not None) and anchor_epoch is None:
        raise ResearchError("RTT probe timestamps are missing from ping output")

    if window_started_at_utc is not None and window_ended_at_utc is not None:
        start_epoch = window_started_at_utc.astimezone(timezone.utc).timestamp()
        end_epoch = window_ended_at_utc.astimezone(timezone.utc).timestamp()
        assert anchor_epoch is not None
        first_sequence = max(
            1,
            math.ceil(first_seen + (start_epoch - anchor_epoch) / interval_seconds),
        )
        last_sequence = math.floor(
            first_seen + (end_epoch - anchor_epoch) / interval_seconds
        )
        if last_sequence < first_sequence:
            raise ResearchError("RTT probe does not overlap the measurement window")
    else:
        first_sequence = min(seen)
        last_sequence = max(seen)

    for sequence in range(first_sequence, last_sequence + 1):
        observed = seen.get(sequence)
        rtt = observed[0] if observed is not None else None
        expected_epoch = (
            anchor_epoch + (sequence - first_seen) * interval_seconds
            if anchor_epoch is not None
            else None
        )
        append_jsonl(
            destination,
            {
                "schema": PROBE_SCHEMA,
                "sequence": sequence,
                "elapsed_seconds": (sequence - first_sequence) * interval_seconds,
                "observed_at_utc": (
                    datetime.fromtimestamp(expected_epoch, timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                    if expected_epoch is not None
                    else None
                ),
                "rtt_ms": rtt,
                "timeout": rtt is None,
            },
        )


def _start_load_client(
    *,
    inventory: NetworkInventory,
    ue_pod: str,
    pdu_address: str,
    target: str,
    port: int,
    target_bps: int,
    protocol: str,
    parallel_flows: int,
    duration_seconds: int,
    repository_root: Path,
    log_path: Path,
) -> base_runtime.ManagedProcess:
    arguments = [
        "iperf3",
        "-c",
        target,
        "-B",
        pdu_address,
        "-p",
        str(port),
        "-t",
        str(duration_seconds),
        "-P",
        str(parallel_flows),
        "-J",
    ]
    if protocol == "udp":
        arguments.extend(("-u", "-b", str(target_bps)))
    command = _kubectl_exec_command(inventory, ue_pod, *arguments)
    return base_runtime._start_process(
        "research background load",
        command,
        cwd=repository_root,
        log_path=log_path,
    )


def _extract_iperf_bps(value: Mapping[str, Any]) -> float | None:
    end = value.get("end")
    if not isinstance(end, Mapping):
        return None
    candidates = (
        end.get("sum_received"),
        end.get("sum_sent"),
        end.get("sum"),
    )
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            bps = candidate.get("bits_per_second")
            if isinstance(bps, (int, float)) and not isinstance(bps, bool):
                return float(bps)
    streams = end.get("streams")
    if isinstance(streams, list):
        totals: list[float] = []
        for stream in streams:
            if not isinstance(stream, Mapping):
                continue
            receiver = stream.get("receiver")
            sender = stream.get("sender")
            candidate = receiver if isinstance(receiver, Mapping) else sender
            if isinstance(candidate, Mapping):
                bps = candidate.get("bits_per_second")
                if isinstance(bps, (int, float)) and not isinstance(bps, bool):
                    totals.append(float(bps))
        if totals:
            return sum(totals)
    return None


def _parse_load_log(
    path: Path,
    destination: Path,
    *,
    target_bps: int,
    protocol: str,
) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ResearchError("unable to read background load log") from exc
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ResearchError("background load did not produce iperf3 JSON")
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ResearchError("background load produced invalid iperf3 JSON") from exc
    if not isinstance(value, Mapping):
        raise ResearchError("background load result is malformed")
    bps = _extract_iperf_bps(value)
    if bps is None:
        raise ResearchError("background load result does not contain measured goodput")
    append_jsonl(
        destination,
        {
            "schema": LOAD_RESULT_SCHEMA,
            "protocol": protocol,
            "target_bps": target_bps,
            "bits_per_second": bps,
        },
    )


def _base_cleanup_reproved(run_directory: Path) -> bool:
    evidence_path = run_directory / "experiment-evidence.json"
    try:
        value = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(value, Mapping):
        return False
    checks = value.get("checks")
    if not isinstance(checks, list):
        return False
    for check in checks:
        if (
            isinstance(check, Mapping)
            and check.get("name") == "cleanup-base-network"
            and check.get("passed") is True
        ):
            return True
    return False


@contextmanager
def _runtime_overrides(
    *,
    spec: ResearchExperimentSpec,
    collector: Callable[..., Any],
) -> Iterator[None]:
    original_builder = base_runtime.build_scenario
    original_collector = base_runtime.collect_mqtt

    def research_builder(**kwargs: Any) -> Any:
        return build_base_scenario(
            **kwargs,
            sensor_period_seconds=spec.sensor_period_seconds,
            cooja_seed=spec.cooja_seed,
        )

    base_runtime.build_scenario = research_builder
    base_runtime.collect_mqtt = collector
    try:
        yield
    finally:
        base_runtime.build_scenario = original_builder
        base_runtime.collect_mqtt = original_collector
