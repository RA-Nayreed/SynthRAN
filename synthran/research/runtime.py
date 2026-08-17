"""Controlled research execution on top of the accepted SynthRAN lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from typing import Any, Mapping, TextIO

from synthran.dependencies import DependencyLock
from synthran.experiment import runtime as base_runtime
from synthran.fiveg_ansible import NetworkInventory
from synthran.network.rfsim import reconcile_rfsim_runtime
from synthran.network.runtime import verify_network_path
from synthran.research import (
    CAPACITY_SCHEMA,
    LOAD_RESULT_SCHEMA,
    MEASUREMENT_WINDOW_SCHEMA,
    NETWORK_SAMPLE_SCHEMA,
    PROBE_SCHEMA,
    ResearchError,
    ResearchExperimentSpec,
    atomic_json,
    build_run_summary,
    load_jsonl,
    save_research_spec,
    save_run_summary,
    write_records_parquet,
)
from synthran.research.collector import collect_mqtt_window
from synthran.research.instrumentation import (
    DEFAULT_RESEARCH_RUN_ROOT,
    ResearchRunResult,
    _base_cleanup_reproved,
    _check_research_tools,
    _extract_iperf_bps,
    _install_target_route,
    _kubectl_exec_command,
    _parse_load_log,
    _parse_probe_log,
    _remove_target_route,
    _runtime_overrides,
    _start_load_client,
    _start_probe,
)
from synthran.research.iperf import (
    OwnedIperfServer,
    start_owned_iperf_server,
    stop_owned_iperf_server,
)
from synthran.research.sampling import ResearchNetworkSampler

_RUNTIME_OVERRIDE_LOCK = threading.Lock()


def execute_research_experiment(
    *,
    spec: ResearchExperimentSpec,
    inventory: NetworkInventory,
    lock: DependencyLock,
    dependency_root: Path,
    network_manifest: Path,
    network_evidence: Path,
    repository_root: Path,
    run_root: Path = DEFAULT_RESEARCH_RUN_ROOT,
    progress: TextIO | None = None,
) -> ResearchRunResult:
    if spec.probe_target is None:
        raise ResearchError("live controlled experiment requires a probe/load target")
    run_directory = run_root.resolve() / spec.run_id
    summary_path = run_directory / "research-summary.json"
    window_path = run_directory / "measurement-window.json"
    probe_path = run_directory / "probe.jsonl"
    network_path = run_directory / "network-samples.jsonl"
    load_path = run_directory / "load.jsonl"
    probe_log = run_directory / "logs" / "research-probe.log"
    load_client_log = run_directory / "logs" / "research-load-client.log"
    load_server_log = run_directory / "logs" / "research-load-server.log"
    instrumentation_errors: list[str] = []

    def report(message: str) -> None:
        if progress is not None:
            print(f"[synthran] research: {message}", file=progress, flush=True)

    def collector(
        scenario: Any,
        *,
        host: str,
        port: int,
        jsonl_path: Path,
        rejected_path: Path,
        minimum_per_sensor: int,
        timeout_seconds: int,
    ) -> Any:
        del minimum_per_sensor, timeout_seconds
        state = reconcile_rfsim_runtime(
            inventory, network_run_id=scenario.network_run_id
        )
        ue_pod = state.ue_pod
        _check_research_tools(
            inventory, ue_pod, load_enabled=spec.load.enabled
        )
        route_installed = _install_target_route(
            inventory,
            ue_pod,
            pdu_address=scenario.pdu_address,
            target=spec.probe_target or "",
        )
        sampler: ResearchNetworkSampler | None = None
        processes: list[base_runtime.ManagedProcess] = []
        load_server: OwnedIperfServer | None = None

        def start_instrumentation() -> None:
            nonlocal load_server
            assert sampler is not None
            sampler.start()
            probe = _start_probe(
                inventory=inventory,
                ue_pod=ue_pod,
                target=spec.probe_target or "",
                duration_seconds=spec.measurement.duration_seconds + 2,
                interval_seconds=spec.measurement.probe_interval_seconds,
                repository_root=repository_root,
                log_path=probe_log,
            )
            processes.append(probe)
            if spec.load.enabled:
                target_bps = spec.load.resolved_target_bps
                assert target_bps is not None
                load_server = start_owned_iperf_server(
                    inventory=inventory,
                    owner_id=spec.run_id,
                    port=spec.load.server_port,
                    repository_root=repository_root,
                    log_path=load_server_log,
                )
                per_stream_bps = max(
                    1, target_bps // spec.load.parallel_flows
                )
                client = _start_load_client(
                    inventory=inventory,
                    ue_pod=ue_pod,
                    pdu_address=scenario.pdu_address,
                    target=spec.probe_target or "",
                    port=spec.load.server_port,
                    target_bps=per_stream_bps,
                    protocol=spec.load.protocol,
                    parallel_flows=spec.load.parallel_flows,
                    duration_seconds=spec.measurement.duration_seconds + 2,
                    repository_root=repository_root,
                    log_path=load_client_log,
                )
                processes.append(client)

        result = None
        try:
            sampler = ResearchNetworkSampler(
                inventory=inventory,
                network_run_id=scenario.network_run_id,
                experiment_run_id=scenario.run_id,
                ue_pod=ue_pod,
                interval_seconds=spec.measurement.sample_interval_seconds,
                destination=network_path,
            )
            if spec.measurement.warmup_seconds:
                report(f"warmup: {spec.measurement.warmup_seconds}s")
            report(
                f"measurement window: {spec.measurement.duration_seconds}s"
            )
            result = collect_mqtt_window(
                scenario,
                host=host,
                port=port,
                jsonl_path=jsonl_path,
                rejected_path=rejected_path,
                duration_seconds=spec.measurement.duration_seconds,
                warmup_seconds=spec.measurement.warmup_seconds,
                on_window_start=start_instrumentation,
            )
            atomic_json(
                window_path,
                {
                    "schema": MEASUREMENT_WINDOW_SCHEMA,
                    "run_id": scenario.run_id,
                    "warmup_seconds": spec.measurement.warmup_seconds,
                    "requested_duration_seconds": spec.measurement.duration_seconds,
                    "started_at_utc": result.started_at_utc.astimezone(
                        timezone.utc
                    )
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "ended_at_utc": result.ended_at_utc.astimezone(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                },
            )
            return result
        finally:
            if sampler is not None:
                try:
                    sampler.stop()
                except Exception as exc:
                    instrumentation_errors.append(str(exc))
            for process in reversed(processes):
                try:
                    if process.process.poll() is None:
                        process.process.wait(timeout=5)
                except Exception:
                    pass
                try:
                    process.stop()
                except Exception as exc:
                    instrumentation_errors.append(f"{process.name}: {exc}")
            if load_server is not None:
                try:
                    stop_owned_iperf_server(inventory, load_server)
                except Exception as exc:
                    instrumentation_errors.append(str(exc))
            if route_installed:
                try:
                    _remove_target_route(
                        inventory,
                        ue_pod,
                        pdu_address=scenario.pdu_address,
                        target=spec.probe_target or "",
                    )
                except Exception as exc:
                    instrumentation_errors.append(str(exc))
            try:
                _parse_probe_log(
                    probe_log,
                    probe_path,
                    interval_seconds=spec.measurement.probe_interval_seconds,
                    window_started_at_utc=(
                        result.started_at_utc if result is not None else None
                    ),
                    window_ended_at_utc=(
                        result.ended_at_utc if result is not None else None
                    ),
                )
            except Exception as exc:
                instrumentation_errors.append(str(exc))
            if spec.load.enabled:
                target_bps = spec.load.resolved_target_bps
                assert target_bps is not None
                try:
                    _parse_load_log(
                        load_client_log,
                        load_path,
                        target_bps=target_bps,
                        protocol=spec.load.protocol,
                    )
                except Exception as exc:
                    instrumentation_errors.append(str(exc))

    with _RUNTIME_OVERRIDE_LOCK:
        with _runtime_overrides(spec=spec, collector=collector):
            base_result = base_runtime.execute_experiment(
                inventory=inventory,
                lock=lock,
                dependency_root=dependency_root,
                network_manifest=network_manifest,
                network_evidence=network_evidence,
                run_id=spec.run_id,
                repository_root=repository_root,
                run_root=run_root,
                collection_seconds=max(
                    30, spec.measurement.duration_seconds
                ),
                minimum_per_sensor=1,
                progress=progress,
            )

    save_research_spec(spec, run_directory / "experiment-spec.json")
    telemetry_records = load_jsonl(run_directory / "telemetry.jsonl")
    probe_records = load_jsonl(probe_path, schema=PROBE_SCHEMA)
    network_records = load_jsonl(network_path, schema=NETWORK_SAMPLE_SCHEMA)
    load_records = load_jsonl(load_path, schema=LOAD_RESULT_SCHEMA)
    summary = build_run_summary(
        spec=spec,
        run_directory=run_directory,
        telemetry_records=telemetry_records,
        probe_records=probe_records,
        network_records=network_records,
        load_records=load_records,
    )
    validity = dict(summary["validity"])
    validity["measurement_window_present"] = window_path.is_file()
    validity["instrumentation_clean"] = not instrumentation_errors
    validity["base_cleanup_reproved"] = _base_cleanup_reproved(run_directory)
    summary["validity"] = validity
    summary["instrumentation_errors"] = instrumentation_errors
    summary["ready_for_campaign_analysis"] = all(validity.values())
    summary["path_acceptance_ready"] = base_result.ready
    save_run_summary(summary, summary_path)

    for source, destination in (
        (probe_records, run_directory / "probe.parquet"),
        (network_records, run_directory / "network-samples.parquet"),
        (load_records, run_directory / "load.parquet"),
    ):
        if source:
            write_records_parquet(source, destination)

    return ResearchRunResult(
        run_id=spec.run_id,
        run_directory=run_directory,
        summary_path=summary_path,
        ready_for_campaign_analysis=(
            summary["ready_for_campaign_analysis"] is True
        ),
        path_acceptance_ready=base_result.ready,
    )


def calibrate_capacity(
    *,
    inventory: NetworkInventory,
    lock: DependencyLock,
    network_run_id: str,
    target: str,
    repository_root: Path,
    output_path: Path,
    duration_seconds: int = 10,
    server_port: int = 5201,
) -> Mapping[str, Any]:
    if duration_seconds < 5 or duration_seconds > 120:
        raise ResearchError(
            "calibration duration must be between 5 and 120 seconds"
        )
    base = verify_network_path(
        inventory=inventory,
        lock=lock,
        run_id=network_run_id,
        timeout_seconds=120,
    )
    if not base.ready:
        raise ResearchError(
            "capacity calibration requires a currently path-proven network"
        )
    state = reconcile_rfsim_runtime(
        inventory, network_run_id=network_run_id
    )
    ue_pod = state.ue_pod
    _check_research_tools(inventory, ue_pod, load_enabled=True)
    route_installed = _install_target_route(
        inventory,
        ue_pod,
        pdu_address=state.pdu_address,
        target=target,
    )

    owner_id = "cal-" + hashlib.sha256(
        f"{network_run_id}:{target}:{server_port}".encode("utf-8")
    ).hexdigest()[:16]
    server: OwnedIperfServer | None = None
    failure: Exception | None = None
    payload: Mapping[str, Any] | None = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        server_log = output_path.with_suffix(".server.log")
        server = start_owned_iperf_server(
            inventory=inventory,
            owner_id=owner_id,
            port=server_port,
            repository_root=repository_root,
            log_path=server_log,
        )
        command = _kubectl_exec_command(
            inventory,
            ue_pod,
            "iperf3",
            "-c",
            target,
            "-B",
            state.pdu_address,
            "-p",
            str(server_port),
            "-t",
            str(duration_seconds),
            "-J",
        )
        result = base_runtime._run(
            command, timeout_seconds=duration_seconds + 20
        )
        if result.returncode != 0:
            raise ResearchError("capacity calibration client failed")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ResearchError(
                "capacity calibration produced invalid iperf3 JSON"
            ) from exc
        if not isinstance(value, Mapping):
            raise ResearchError("capacity calibration result is malformed")
        capacity = _extract_iperf_bps(value)
        if capacity is None or capacity <= 0:
            raise ResearchError(
                "capacity calibration did not report positive throughput"
            )
        payload = {
            "schema": CAPACITY_SCHEMA,
            "network_run_id": network_run_id,
            "ue_pod": ue_pod,
            "ue_interface": "tun_srsue1",
            "pdu_address": state.pdu_address,
            "target": target,
            "duration_seconds": duration_seconds,
            "reference_capacity_bps": round(capacity),
            "measured_at_utc": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        output_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        failure = exc

    cleanup_errors: list[str] = []
    if server is not None:
        try:
            stop_owned_iperf_server(inventory, server)
        except Exception as exc:
            cleanup_errors.append(f"iperf3 server: {exc}")
    if route_installed:
        try:
            _remove_target_route(
                inventory,
                ue_pod,
                pdu_address=state.pdu_address,
                target=target,
            )
        except Exception as exc:
            cleanup_errors.append(f"target route: {exc}")

    if failure is not None and cleanup_errors:
        raise ResearchError(
            "capacity calibration failed and cleanup failed closed: "
            f"{failure}; {'; '.join(cleanup_errors)}"
        ) from failure
    if failure is not None:
        raise failure
    if cleanup_errors:
        raise ResearchError(
            "capacity calibration cleanup failed closed: "
            + "; ".join(cleanup_errors)
        )
    assert payload is not None
    return payload
