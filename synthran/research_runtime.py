"""Live research execution built on the accepted experiment runtime."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shlex
import threading
import time
from typing import Any, Mapping, TextIO

from synthran.dependencies import DependencyLock
from synthran.experiment import ExperimentError, build_scenario as build_base_scenario
from synthran.experiment_resources import CENTRAL_PORT, EDGE_CONTAINER, RUN_LABEL
import synthran.experiment_runtime as experiment_runtime
from synthran.experiment_runtime import ExperimentRunResult, _core_address, _run
from synthran.fiveg_ansible import NetworkInventory
from synthran.live_preflight import LivePreflightError, ssh_command
from synthran.research import (
    RESEARCH_EVIDENCE_SCHEMA,
    RESEARCH_SAMPLE_SCHEMA,
    RESEARCH_WINDOW_SCHEMA,
    CampaignPlan,
    LoadProfile,
    ResearchSpec,
    analyze_research_run,
    append_jsonl,
    save_research_spec,
)

KUBERNETES_NAMESPACE = "open5gs"
_RESEARCH_EXECUTION_LOCK = threading.Lock()
PING_RE = re.compile(r"time[=<]([0-9]+(?:\.[0-9]+)?)\s*ms")


@contextmanager
def _scenario_parameters(spec: ResearchSpec):
    original = experiment_runtime.build_scenario

    def research_builder(
        *,
        run_id: str,
        network_manifest: Path,
        network_evidence: Path,
        sensor_period_seconds: int = 10,
        cooja_seed: int = 424242,
        serial_socket_port: int = 60001,
    ):
        return build_base_scenario(
            run_id=run_id,
            network_manifest=network_manifest,
            network_evidence=network_evidence,
            sensor_period_seconds=spec.sensor_period_seconds,
            cooja_seed=spec.cooja_seed,
            serial_socket_port=serial_socket_port,
        )

    experiment_runtime.build_scenario = research_builder
    try:
        yield
    finally:
        experiment_runtime.build_scenario = original


@dataclass(frozen=True)
class ResearchRunResult:
    experiment: ExperimentRunResult
    summary_path: Path
    valid: bool


def _remote_command(
    inventory: NetworkInventory, *args: str, timeout_seconds: int = 15
):
    try:
        command = ssh_command(inventory.core_node, *args)
    except LivePreflightError as exc:
        raise ExperimentError(str(exc)) from exc
    return _run(command, timeout_seconds=timeout_seconds)


def _kubectl_json(inventory: NetworkInventory, *args: str) -> Mapping[str, Any]:
    result = _remote_command(
        inventory,
        "env",
        "KUBECONFIG=/etc/kubernetes/admin.conf",
        "kubectl",
        *args,
        "-o",
        "json",
    )
    if result.returncode != 0:
        raise ExperimentError("research Kubernetes discovery failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ExperimentError("research Kubernetes discovery returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise ExperimentError("research Kubernetes discovery returned malformed data")
    return value


def _discover_research_ue_pod(inventory: NetworkInventory, run_id: str) -> str | None:
    payload = _kubectl_json(inventory, "get", "pods", "-n", KUBERNETES_NAMESPACE)
    items = payload.get("items")
    if not isinstance(items, list):
        raise ExperimentError("research pod discovery returned malformed data")
    matches: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        status = item.get("status")
        spec = item.get("spec")
        if not isinstance(metadata, dict) or not isinstance(status, dict) or not isinstance(spec, dict):
            continue
        annotations = metadata.get("annotations")
        if not isinstance(annotations, dict) or annotations.get(RUN_LABEL) != run_id:
            continue
        if status.get("phase") != "Running":
            continue
        containers = spec.get("containers")
        names = (
            {
                str(container.get("name"))
                for container in containers
                if isinstance(container, dict) and container.get("name")
            }
            if isinstance(containers, list)
            else set()
        )
        if {"ue", EDGE_CONTAINER}.issubset(names):
            name = metadata.get("name")
            if isinstance(name, str):
                matches.append(name)
    if len(matches) > 1:
        raise ExperimentError("multiple run-owned UE pods were found during research observation")
    return matches[0] if matches else None


def _exec_container(
    inventory: NetworkInventory,
    pod: str,
    container: str,
    *args: str,
    timeout_seconds: int = 10,
):
    return _remote_command(
        inventory,
        "env",
        "KUBECONFIG=/etc/kubernetes/admin.conf",
        "kubectl",
        "exec",
        "-n",
        KUBERNETES_NAMESPACE,
        pod,
        "-c",
        container,
        "--",
        *args,
        timeout_seconds=timeout_seconds,
    )


def _exec_ue(
    inventory: NetworkInventory, pod: str, *args: str, timeout_seconds: int = 10
):
    return _exec_container(
        inventory, pod, "ue", *args, timeout_seconds=timeout_seconds
    )


def _interface_bytes(inventory: NetworkInventory, pod: str) -> tuple[int, int]:
    result = _exec_ue(
        inventory,
        pod,
        "sh",
        "-c",
        "cat /sys/class/net/tun_srsue1/statistics/tx_bytes; "
        "cat /sys/class/net/tun_srsue1/statistics/rx_bytes",
    )
    if result.returncode != 0:
        raise ExperimentError("unable to read tun_srsue1 research counters")
    values = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(values) != 2 or not all(value.isdigit() for value in values):
        raise ExperimentError("tun_srsue1 research counters are malformed")
    return int(values[0]), int(values[1])


def _route_uses_tun(
    inventory: NetworkInventory, pod: str, target: str
) -> bool:
    result = _exec_ue(inventory, pod, "ip", "route", "get", target)
    return result.returncode == 0 and "dev tun_srsue1" in result.stdout


def _probe_research_tools(
    inventory: NetworkInventory,
    pod: str,
    *,
    require_load_tools: bool,
) -> None:
    ue = _exec_ue(inventory, pod, "sh", "-c", "command -v ping >/dev/null 2>&1")
    if ue.returncode != 0:
        raise ExperimentError("research RTT probe requires ping in the UE container")
    if not require_load_tools:
        return
    result = _exec_container(
        inventory,
        pod,
        EDGE_CONTAINER,
        "sh",
        "-c",
        "for tool in mosquitto_pub head tr sleep; do "
        "command -v \"$tool\" >/dev/null 2>&1 || exit 9; done",
    )
    if result.returncode != 0:
        raise ExperimentError("research background load tools are unavailable in the edge container")


def _probe_rtt(
    inventory: NetworkInventory, pod: str, target: str
) -> tuple[bool, float | None]:
    result = _exec_ue(
        inventory,
        pod,
        "ping",
        "-I",
        "tun_srsue1",
        "-c",
        "1",
        "-W",
        "1",
        target,
        timeout_seconds=5,
    )
    if result.returncode != 0:
        return False, None
    match = PING_RE.search(result.stdout)
    if match is None:
        return False, None
    return True, float(match.group(1))


def _load_command(
    *, target: str, run_id: str, target_kbps: float, payload_bytes: int
) -> str:
    if target_kbps <= 0:
        raise ExperimentError("research background load target must be positive")
    sleep_seconds = payload_bytes * 8.0 / (target_kbps * 1000.0)
    payload_length = max(1, payload_bytes - 1)
    topic = f"synthran/{run_id}/background"
    return (
        "set -eu; "
        f"payload=$(head -c {payload_length} /dev/zero | tr '\\000' x); "
        "while :; do "
        f"printf '%s\\n' \"$payload\"; sleep {sleep_seconds:.6f}; "
        "done | "
        f"mosquitto_pub -h {shlex.quote(target)} -p {CENTRAL_PORT} "
        f"-t {shlex.quote(topic)} -l -q 0"
    )


class ResearchObserver:
    def __init__(
        self,
        *,
        inventory: NetworkInventory,
        spec: ResearchSpec,
        run_directory: Path,
        progress: TextIO | None,
    ) -> None:
        self.inventory = inventory
        self.spec = spec
        self.run_directory = run_directory
        self.progress = progress
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.measurement_complete = threading.Event()
        self.error: Exception | None = None
        self.thread = threading.Thread(
            target=self._run,
            name=f"research-{spec.run_id}",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=20)
        if self.thread.is_alive():
            raise ExperimentError("research observer did not stop cleanly")
        if self.error is not None:
            raise ExperimentError(f"research observer failed: {self.error}")

    def _report(self, message: str) -> None:
        if self.progress is not None:
            print(f"[synthran] research: {message}", file=self.progress, flush=True)

    def _run(self) -> None:
        try:
            self._observe()
        except Exception as exc:
            self.error = exc
            self.stop_event.set()

    def _wait_for_path(self) -> tuple[str, str]:
        core = _core_address(self.inventory)
        deadline = time.monotonic() + 240
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            pod = _discover_research_ue_pod(self.inventory, self.spec.run_id)
            if pod is not None:
                try:
                    _interface_bytes(self.inventory, pod)
                    if _route_uses_tun(self.inventory, pod, core):
                        return pod, core
                except ExperimentError:
                    pass
            self.stop_event.wait(1)
        raise ExperimentError("run-owned tun_srsue1 path was not observable for research measurements")

    def _start_load(self, pod: str, core: str):
        if self.spec.load.mode == "baseline":
            return None
        command = _load_command(
            target=core,
            run_id=self.spec.run_id,
            target_kbps=self.spec.load.target_kbps,
            payload_bytes=self.spec.load.payload_bytes,
        )
        try:
            ssh = ssh_command(
                self.inventory.core_node,
                "env",
                "KUBECONFIG=/etc/kubernetes/admin.conf",
                "kubectl",
                "exec",
                "-n",
                KUBERNETES_NAMESPACE,
                pod,
                "-c",
                EDGE_CONTAINER,
                "--",
                "sh",
                "-c",
                command,
            )
        except LivePreflightError as exc:
            raise ExperimentError(str(exc)) from exc
        process = experiment_runtime._start_process(
            "research background MQTT load",
            ssh,
            cwd=self.run_directory,
            log_path=self.run_directory / "logs" / "research-load.log",
        )
        self._report(f"background target {self.spec.load.target_kbps:.1f} kbps")
        return process

    def _wait_for_telemetry(self) -> None:
        telemetry_path = self.run_directory / "telemetry.jsonl"
        deadline = time.monotonic() + 240
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            try:
                if telemetry_path.is_file() and telemetry_path.stat().st_size > 0:
                    return
            except OSError:
                pass
            self.stop_event.wait(0.5)
        if not self.stop_event.is_set():
            raise ExperimentError("research measurement window did not observe telemetry start")

    def _observe(self) -> None:
        pod, core = self._wait_for_path()
        _probe_research_tools(
            self.inventory,
            pod,
            require_load_tools=self.spec.load.mode in {"congestion", "calibration"},
        )
        load_process = self._start_load(pod, core)
        self.ready_event.set()
        try:
            self._wait_for_telemetry()
            if self.stop_event.is_set():
                return
            if self.spec.warmup_seconds:
                self._report(f"warmup {self.spec.warmup_seconds}s")
                if self.stop_event.wait(self.spec.warmup_seconds):
                    return

            previous_time: float | None = None
            previous_tx: int | None = None
            measurement_started = time.monotonic()
            measurement_started_utc = datetime.now(timezone.utc)
            measurement_deadline = measurement_started + self.spec.measurement_seconds
            self._report(f"measurement {self.spec.measurement_seconds}s")
            while not self.stop_event.is_set() and time.monotonic() < measurement_deadline:
                now = time.monotonic()
                tx, rx = _interface_bytes(self.inventory, pod)
                success, rtt = _probe_rtt(self.inventory, pod, core)
                append_jsonl(
                    self.run_directory / "research-probe.jsonl",
                    {
                        "schema": RESEARCH_SAMPLE_SCHEMA,
                        "monotonic_seconds": now,
                        "success": success,
                        "rtt_ms": rtt,
                    },
                )
                append_jsonl(
                    self.run_directory / "research-network.jsonl",
                    {
                        "schema": RESEARCH_SAMPLE_SCHEMA,
                        "monotonic_seconds": now,
                        "ue_tx_bytes": tx,
                        "ue_rx_bytes": rx,
                    },
                )
                if previous_time is not None and previous_tx is not None and now > previous_time:
                    measured = max(0, tx - previous_tx) * 8.0 / (now - previous_time) / 1000.0
                    append_jsonl(
                        self.run_directory / "research-load.jsonl",
                        {
                            "schema": RESEARCH_SAMPLE_SCHEMA,
                            "monotonic_seconds": now,
                            "measured_kbps": measured,
                        },
                    )
                previous_time = now
                previous_tx = tx
                self.stop_event.wait(self.spec.sample_interval_seconds)

            if self.stop_event.is_set():
                return
            measurement_ended_utc = datetime.now(timezone.utc)
            measurement_ended = time.monotonic()
            (self.run_directory / "research-window.json").write_text(
                json.dumps(
                    {
                        "schema": RESEARCH_WINDOW_SCHEMA,
                        "start_utc": measurement_started_utc.isoformat().replace("+00:00", "Z"),
                        "end_utc": measurement_ended_utc.isoformat().replace("+00:00", "Z"),
                        "start_monotonic_seconds": measurement_started,
                        "end_monotonic_seconds": measurement_ended,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self.measurement_complete.set()
        finally:
            if load_process is not None:
                load_process.stop()


def execute_research_run(
    *,
    spec: ResearchSpec,
    inventory: NetworkInventory,
    lock: DependencyLock,
    dependency_root: Path,
    network_manifest: Path,
    network_evidence: Path,
    repository_root: Path,
    run_root: Path,
    progress: TextIO | None = None,
) -> ResearchRunResult:
    run_directory = run_root.resolve() / spec.run_id
    observer = ResearchObserver(
        inventory=inventory,
        spec=spec,
        run_directory=run_directory,
        progress=progress,
    )
    observer.start()
    experiment: ExperimentRunResult | None = None
    observer_error: Exception | None = None
    try:
        with _RESEARCH_EXECUTION_LOCK, _scenario_parameters(spec):
            experiment = experiment_runtime.execute_experiment(
                inventory=inventory,
                lock=lock,
                dependency_root=dependency_root,
                network_manifest=network_manifest,
                network_evidence=network_evidence,
                run_id=spec.run_id,
                repository_root=repository_root,
                run_root=run_root,
                collection_seconds=spec.collection_timeout_seconds,
                minimum_per_sensor=spec.minimum_per_sensor,
                progress=progress,
            )
    finally:
        try:
            observer.stop()
        except Exception as exc:
            observer_error = exc

    if experiment is None:
        if observer_error is not None:
            raise observer_error
        raise ExperimentError("research experiment did not produce a result")

    save_research_spec(spec, experiment.run_directory / "research-spec.json")
    measurement_valid = observer.measurement_complete.is_set()
    summary_path = experiment.run_directory / "research-summary.json"
    if measurement_valid:
        summary = analyze_research_run(experiment.run_directory)
    else:
        summary = {}
    load_summary = summary.get("load") if isinstance(summary, dict) else None
    probe_summary = summary.get("probe") if isinstance(summary, dict) else None
    achieved = (
        load_summary.get("target_achievement_ratio")
        if isinstance(load_summary, dict)
        else None
    )
    if spec.load.mode == "baseline":
        load_valid = True
    elif spec.load.mode == "calibration":
        measured = (
            load_summary.get("measured_kbps_median")
            if isinstance(load_summary, dict)
            else None
        )
        load_valid = isinstance(measured, (int, float)) and float(measured) > 0
    else:
        load_valid = isinstance(achieved, (int, float)) and 0.75 <= float(achieved) <= 1.25
    probe_valid = (
        isinstance(probe_summary, dict)
        and isinstance(probe_summary.get("probe_successes"), int)
        and int(probe_summary["probe_successes"]) > 0
    )
    valid = (
        experiment.ready
        and observer_error is None
        and measurement_valid
        and load_valid
        and probe_valid
    )
    evidence = {
        "schema": RESEARCH_EVIDENCE_SCHEMA,
        "run_id": spec.run_id,
        "campaign_id": spec.campaign_id,
        "valid": valid,
        "checks": [
            {"name": "iot-to-5g-path", "passed": experiment.ready},
            {"name": "research-observer", "passed": observer_error is None},
            {"name": "measurement-window", "passed": measurement_valid},
            {"name": "rtt-probe", "passed": probe_valid},
            {"name": "background-load", "passed": load_valid},
        ],
    }
    (experiment.run_directory / "research-evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if observer_error is not None:
        raise observer_error
    return ResearchRunResult(
        experiment=experiment,
        summary_path=summary_path,
        valid=valid,
    )


@dataclass(frozen=True)
class ResearchCampaignResult:
    campaign_id: str
    runs: tuple[ResearchRunResult, ...]

    @property
    def valid(self) -> bool:
        return bool(self.runs) and all(run.valid for run in self.runs)


def execute_research_campaign(
    *,
    plan: CampaignPlan,
    inventory: NetworkInventory,
    lock: DependencyLock,
    dependency_root: Path,
    network_manifest: Path,
    network_evidence: Path,
    repository_root: Path,
    run_root: Path,
    warmup_seconds: int,
    measurement_seconds: int,
    sample_interval_seconds: float,
    payload_bytes: int,
    sensor_period_seconds: int = 10,
    progress: TextIO | None = None,
) -> ResearchCampaignResult:
    results: list[ResearchRunResult] = []
    for campaign_run in plan.runs:
        load = (
            LoadProfile("baseline", payload_bytes=payload_bytes)
            if campaign_run.condition == "baseline"
            else LoadProfile(
                "congestion",
                target_fraction=campaign_run.target_fraction,
                reference_kbps=plan.reference_kbps,
                payload_bytes=payload_bytes,
            )
        )
        spec = ResearchSpec(
            campaign_id=plan.campaign_id,
            run_id=campaign_run.run_id,
            network_run_id=plan.network_run_id,
            condition=campaign_run.condition,
            cooja_seed=campaign_run.seed,
            sensor_period_seconds=sensor_period_seconds,
            warmup_seconds=warmup_seconds,
            measurement_seconds=measurement_seconds,
            sample_interval_seconds=sample_interval_seconds,
            load=load,
        )
        if progress is not None:
            print(
                f"[synthran] research campaign: run {campaign_run.ordinal}/{len(plan.runs)} "
                f"{campaign_run.run_id}",
                file=progress,
                flush=True,
            )
        result = execute_research_run(
            spec=spec,
            inventory=inventory,
            lock=lock,
            dependency_root=dependency_root,
            network_manifest=network_manifest,
            network_evidence=network_evidence,
            repository_root=repository_root,
            run_root=run_root,
            progress=progress,
        )
        results.append(result)
        if not result.valid:
            break
    return ResearchCampaignResult(plan.campaign_id, tuple(results))
