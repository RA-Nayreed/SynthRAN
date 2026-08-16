"""Operator-triggered integrated Phase 3 runtime.

This runner consumes an already path-proven network deployment. It creates
only run-scoped Phase 3 resources, temporarily adds an MQTT sidecar to the
run-owned srsUE Deployment, collects deterministic telemetry, restores the
srsUE Deployment, and reproves the accepted network after cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence, TextIO

from synthran.dependencies import DependencyLock
from synthran.fiveg_ansible import NetworkInventory
from synthran.live_preflight import CommandResult, LivePreflightError, ssh_command
from synthran.network_runtime import verify_network_path
from synthran.phase3_collector import collect_mqtt
from synthran.phase3_k8s import (
    CENTRAL_PORT,
    EDGE_CONTAINER,
    RUN_LABEL,
    json_document,
    names,
    render_edge_cleanup_patch,
    render_edge_patch,
    render_phase3_objects,
)
from synthran.phase3_proxy import CountedTcpProxy
from synthran.phase3_render import write_run_inputs
from synthran.phase3_runtime import (
    Phase3Check,
    Phase3Error,
    Phase3Scenario,
    build_offline_data_evidence,
    build_scenario,
    load_jsonl,
    save_phase3_evidence,
    validate_run_id,
    write_parquet,
)


DEFAULT_RUN_ROOT = Path(".synthran/experiments")
DEFAULT_COLLECTION_SECONDS = 180
DEFAULT_MINIMUM_PER_SENSOR = 3
LOCAL_EDGE_FORWARD_PORT = 18883
LOCAL_CENTRAL_FORWARD_PORT = 18885
KUBERNETES_NAMESPACE = "open5gs"


@dataclass(frozen=True)
class Phase3RunResult:
    run_id: str
    run_directory: Path
    evidence_path: Path
    ready: bool


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen[str]
    log_path: Path
    log_stream: TextIO

    def stop(self) -> None:
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=5)
        self.log_stream.close()


def _run(
    command: Sequence[str],
    *,
    timeout_seconds: int = 60,
    cwd: Path | None = None,
    input_text: str | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise Phase3Error(f"required command was not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise Phase3Error("Phase 3 command timed out") from exc
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _checked(
    command: Sequence[str],
    *,
    label: str,
    timeout_seconds: int = 60,
    cwd: Path | None = None,
    input_text: str | None = None,
) -> str:
    result = _run(
        command,
        timeout_seconds=timeout_seconds,
        cwd=cwd,
        input_text=input_text,
    )
    if result.returncode != 0:
        raise Phase3Error(f"{label} failed")
    return result.stdout


def _remote(
    inventory: NetworkInventory,
    *remote_command: str,
    label: str,
    timeout_seconds: int = 60,
) -> str:
    try:
        command = ssh_command(inventory.core_node, *remote_command)
    except LivePreflightError as exc:
        raise Phase3Error(str(exc)) from exc
    return _checked(command, label=label, timeout_seconds=timeout_seconds)


def _remote_json(
    inventory: NetworkInventory,
    command: str,
    *,
    label: str,
    timeout_seconds: int = 60,
) -> Mapping[str, Any]:
    output = _remote(
        inventory,
        "sh",
        "-c",
        command,
        label=label,
        timeout_seconds=timeout_seconds,
    )
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise Phase3Error(f"{label} did not return JSON") from exc
    if not isinstance(value, dict):
        raise Phase3Error(f"{label} did not return one JSON object")
    return value


def _one_name(payload: Mapping[str, Any], *, label: str) -> str:
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise Phase3Error(f"expected exactly one {label}")
    metadata = items[0].get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str):
        raise Phase3Error(f"{label} metadata is malformed")
    return str(metadata["name"])


def _core_address(inventory: NetworkInventory) -> str:
    value = inventory.core_node.variables.get("ansible_host", inventory.core_node.name)
    try:
        ipaddress.ip_address(value)
    except ValueError as exc:
        raise Phase3Error(
            "Phase 3 requires the core ansible_host to be a literal IP address"
        ) from exc
    return value


def _validate_contiki_checkout(lock: DependencyLock, dependency_root: Path) -> Path:
    dependency = next((item for item in lock.git if item.name == "contiki_ng"), None)
    if dependency is None:
        raise Phase3Error("dependency lock does not define Contiki-NG")
    checkout = dependency_root.resolve() / Path(str(dependency.checkout))
    if not checkout.is_dir():
        raise Phase3Error("pinned Contiki-NG checkout is missing; run synthran deps sync")
    head = _checked(
        ("git", "-C", str(checkout), "rev-parse", "HEAD"),
        label="Contiki-NG commit check",
    ).strip()
    if head != dependency.commit:
        raise Phase3Error("Contiki-NG checkout is not at the locked commit")
    status = _checked(
        (
            "git",
            "-C",
            str(checkout),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ),
        label="Contiki-NG cleanliness check",
    )
    if status.strip():
        raise Phase3Error("Contiki-NG checkout has tracked modifications")
    return checkout


def _copy_sensor_source(repository_root: Path, run_directory: Path) -> None:
    source = repository_root.resolve() / "deploy" / "iot" / "sensor"
    destination = run_directory / "sensor"
    for name in ("Makefile", "synthran-sensor.c"):
        candidate = source / name
        if not candidate.is_file():
            raise Phase3Error(f"Phase 3 sensor source is missing: {name}")
        shutil.copy2(candidate, destination / name)


def _wait_tcp(
    host: str,
    port: int,
    *,
    timeout_seconds: int = 60,
    family: int = socket.AF_INET,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        try:
            sock.connect((host, port))
            return
        except OSError:
            time.sleep(0.5)
        finally:
            sock.close()
    raise Phase3Error(f"TCP endpoint {host}:{port} did not become ready")


def _start_process(
    name: str,
    command: Sequence[str],
    *,
    cwd: Path,
    log_path: Path,
) -> ManagedProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = log_path.open("w", encoding="utf-8", newline="\n")
    try:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as exc:
        stream.close()
        raise Phase3Error(f"unable to start {name}") from exc
    return ManagedProcess(name, process, log_path, stream)


def _ssh_tunnel_command(
    inventory: NetworkInventory,
    *,
    local_port: int,
    remote_port: int,
    remote_command: str,
) -> tuple[str, ...]:
    try:
        base = list(ssh_command(inventory.core_node))
    except LivePreflightError as exc:
        raise Phase3Error(str(exc)) from exc
    if not base:
        raise Phase3Error("unable to construct strict SSH tunnel")
    target = base.pop()
    base.extend(
        (
            "-o",
            "ExitOnForwardFailure=yes",
            "-L",
            f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}",
            target,
            remote_command,
        )
    )
    return tuple(base)


def _kubectl_apply_object(
    inventory: NetworkInventory,
    value: Mapping[str, Any],
    *,
    label: str,
) -> None:
    try:
        command = ssh_command(
            inventory.core_node,
            "sh",
            "-c",
            "KUBECONFIG=/etc/kubernetes/admin.conf kubectl apply -f -",
        )
    except LivePreflightError as exc:
        raise Phase3Error(str(exc)) from exc
    result = _run(command, input_text=json.dumps(value), timeout_seconds=60)
    if result.returncode != 0:
        raise Phase3Error(f"{label} failed")


def _kubectl_patch_deployment(
    inventory: NetworkInventory,
    deployment: str,
    patch: Mapping[str, Any],
    *,
    label: str,
) -> None:
    patch_text = shlex.quote(json_document(patch))
    _remote(
        inventory,
        "sh",
        "-c",
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl patch deployment "
        f"{shlex.quote(deployment)} -n {KUBERNETES_NAMESPACE} "
        f"--type=strategic -p {patch_text}",
        label=label,
    )


def _wait_rollout(inventory: NetworkInventory, deployment: str, *, label: str) -> None:
    _remote(
        inventory,
        "sh",
        "-c",
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl rollout status deployment/"
        f"{shlex.quote(deployment)} -n {KUBERNETES_NAMESPACE} --timeout=180s",
        label=label,
        timeout_seconds=200,
    )


def _discover_ue_deployment(inventory: NetworkInventory, network_run_id: str) -> str:
    payload = _remote_json(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl get deployments "
        f"-n {KUBERNETES_NAMESPACE} "
        f"-l app=srsran,component=ue,synthran.run/id={shlex.quote(network_run_id)} "
        "-o json",
        label="srsUE Deployment discovery",
    )
    return _one_name(payload, label="run-owned srsUE Deployment")


def _discover_ue_pod(inventory: NetworkInventory, network_run_id: str) -> str:
    payload = _remote_json(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl get pods "
        f"-n {KUBERNETES_NAMESPACE} "
        f"-l app=srsran,component=ue,synthran.run/id={shlex.quote(network_run_id)} "
        "-o json",
        label="srsUE pod discovery",
    )
    return _one_name(payload, label="run-owned srsUE pod")


def _interface_counter(
    inventory: NetworkInventory,
    pod: str,
    interface: str,
    counter: str,
) -> int:
    if counter not in {"rx_bytes", "tx_bytes"}:
        raise Phase3Error("unsupported interface counter")
    output = _remote(
        inventory,
        "sh",
        "-c",
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(pod)} -c ue -- "
        f"cat /sys/class/net/{shlex.quote(interface)}/statistics/{counter}",
        label=f"{interface} {counter} probe",
    ).strip()
    if not output.isdigit():
        raise Phase3Error(f"{interface} {counter} probe returned invalid data")
    return int(output)


def _add_ue_route(inventory: NetworkInventory, pod: str, core_address: str) -> None:
    destination = f"{core_address}/32"
    _remote(
        inventory,
        "sh",
        "-c",
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(pod)} -c ue -- "
        f"ip route replace {shlex.quote(destination)} dev tun_srsue1",
        label="UE Phase 3 route installation",
    )
    route = _remote(
        inventory,
        "sh",
        "-c",
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(pod)} -c ue -- "
        f"ip -j route get {shlex.quote(core_address)}",
        label="UE Phase 3 route proof",
    )
    try:
        payload = json.loads(route)
    except json.JSONDecodeError as exc:
        raise Phase3Error("UE Phase 3 route proof did not return JSON") from exc
    if not isinstance(payload, list) or not any(
        isinstance(item, dict) and item.get("dev") == "tun_srsue1" for item in payload
    ):
        raise Phase3Error("central MQTT destination is not routed through tun_srsue1")


def _restart_edge_sidecar(inventory: NetworkInventory, pod: str) -> None:
    # The first bridge attempt can occur before the explicit 5G route is added.
    # Killing only the sidecar's PID 1 lets kubelet restart it against that route.
    _remote(
        inventory,
        "sh",
        "-c",
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(pod)} -c {EDGE_CONTAINER} -- "
        "sh -c 'kill -TERM 1' || true",
        label="edge MQTT sidecar restart",
    )


def _delete_phase3_objects(inventory: NetworkInventory, run_id: str) -> None:
    _remote(
        inventory,
        "sh",
        "-c",
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl delete deployment,configmap "
        f"-n {KUBERNETES_NAMESPACE} -l {RUN_LABEL}={shlex.quote(run_id)} "
        "--ignore-not-found=true --wait=true",
        label="Phase 3 exact-run Kubernetes cleanup",
        timeout_seconds=180,
    )


def _render_manifest(
    scenario: Phase3Scenario,
    *,
    status: str,
    scenario_path: Path,
    failure: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "synthran/phase3-run/v1alpha1",
        "run_id": scenario.run_id,
        "network_run_id": scenario.network_run_id,
        "status": status,
        "scenario": scenario_path.name,
        "updated_at_utc": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "reservation_action": "none",
        "network_deployment_action": "none",
    }
    if failure:
        payload["failure"] = failure
    return payload


def _save_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _cleanup_live_resources(
    *,
    inventory: NetworkInventory,
    lock: DependencyLock,
    scenario: Phase3Scenario,
    ue_deployment: str | None,
) -> Phase3Check:
    errors: list[str] = []
    if ue_deployment is not None:
        try:
            _kubectl_patch_deployment(
                inventory,
                ue_deployment,
                render_edge_cleanup_patch(),
                label="srsUE Phase 3 sidecar cleanup",
            )
            _wait_rollout(inventory, ue_deployment, label="srsUE cleanup rollout")
        except Exception as exc:
            errors.append(f"sidecar restore: {exc}")
    try:
        _delete_phase3_objects(inventory, scenario.run_id)
    except Exception as exc:
        errors.append(f"run-scoped object cleanup: {exc}")
    try:
        restored = verify_network_path(
            inventory=inventory,
            lock=lock,
            run_id=scenario.network_run_id,
            timeout_seconds=120,
        )
        if not restored.ready:
            errors.append("accepted network path did not reprove after cleanup")
    except Exception as exc:
        errors.append(f"accepted network reproof: {exc}")
    if errors:
        return Phase3Check(
            "cleanup-base-network",
            False,
            "cleanup failed closed: " + "; ".join(errors),
        )
    return Phase3Check(
        "cleanup-base-network",
        True,
        "Phase 3 resources removed and accepted network path reproven",
    )


def execute_phase3(
    *,
    inventory: NetworkInventory,
    lock: DependencyLock,
    dependency_root: Path,
    network_manifest: Path,
    network_evidence: Path,
    run_id: str,
    repository_root: Path,
    run_root: Path = DEFAULT_RUN_ROOT,
    collection_seconds: int = DEFAULT_COLLECTION_SECONDS,
    minimum_per_sensor: int = DEFAULT_MINIMUM_PER_SENSOR,
    progress: TextIO | None = None,
) -> Phase3RunResult:
    """Run the complete 10-sensor path against a proven network baseline."""

    def report(message: str) -> None:
        if progress is not None:
            print(f"[synthran] {message}", file=progress, flush=True)

    if sys.platform != "linux":
        raise Phase3Error("live Phase 3 execution requires Linux")
    if os.environ.get("CONDA_DEFAULT_ENV") != "synthran":
        raise Phase3Error(
            "live Phase 3 execution requires the active synthran Conda environment"
        )
    if collection_seconds < 30 or collection_seconds > 3600:
        raise Phase3Error("collection duration must be between 30 and 3600 seconds")
    if minimum_per_sensor < 1 or minimum_per_sensor > 100:
        raise Phase3Error("minimum events per sensor must be between 1 and 100")

    scenario = build_scenario(
        run_id=validate_run_id(run_id),
        network_manifest=network_manifest,
        network_evidence=network_evidence,
    )
    contiki = _validate_contiki_checkout(lock, dependency_root)
    core_address = _core_address(inventory)

    report("network-prerequisite: verifying path-proven baseline...")
    base = verify_network_path(
        inventory=inventory,
        lock=lock,
        run_id=scenario.network_run_id,
        timeout_seconds=120,
    )
    if not base.ready:
        raise Phase3Error("accepted network no longer satisfies path proof")
    report("network-prerequisite: OK")

    run_root = run_root.resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    run_directory = run_root / scenario.run_id
    try:
        run_directory.mkdir()
    except FileExistsError as exc:
        raise Phase3Error("experiment run directory already exists; choose a new run ID") from exc

    logs = run_directory / "logs"
    logs.mkdir()
    _, csc, scenario_path = write_run_inputs(
        scenario,
        run_directory=run_directory,
    )
    _copy_sensor_source(repository_root, run_directory)
    manifest_path = run_directory / "manifest.json"
    evidence_path = run_directory / "phase3-evidence.json"
    jsonl_path = run_directory / "telemetry.jsonl"
    rejected_path = run_directory / "rejected-events.jsonl"
    parquet_path = run_directory / "telemetry.parquet"
    _save_manifest(
        manifest_path,
        _render_manifest(scenario, status="running", scenario_path=scenario_path),
    )

    processes: list[ManagedProcess] = []
    proxy: CountedTcpProxy | None = None
    ue_deployment: str | None = None
    extra_checks: list[Phase3Check] = []
    failure: str | None = None

    try:
        report("contiki-submodules: synchronizing pinned submodules...")
        _checked(
            (
                "git",
                "-C",
                str(contiki),
                "submodule",
                "update",
                "--init",
                "--recursive",
            ),
            label="Contiki-NG submodule synchronization",
            timeout_seconds=600,
        )
        report("contiki-submodules: OK")

        report("tunslip6-build: running...")
        _checked(
            ("make", "-C", str(contiki / "tools" / "serial-io"), "tunslip6"),
            label="tunslip6 build",
            timeout_seconds=180,
        )
        report("tunslip6-build: OK")

        ue_deployment = _discover_ue_deployment(inventory, scenario.network_run_id)
        resource_names = names(scenario)
        for index, value in enumerate(
            render_phase3_objects(
                scenario,
                lock=lock,
                core_node=inventory.core_node.name,
                core_address=core_address,
            ),
            start=1,
        ):
            _kubectl_apply_object(
                inventory,
                value,
                label=f"Phase 3 Kubernetes object {index}",
            )

        _remote(
            inventory,
            "sh",
            "-c",
            "KUBECONFIG=/etc/kubernetes/admin.conf kubectl rollout status deployment/"
            f"{resource_names['central_deployment']} -n {KUBERNETES_NAMESPACE} "
            "--timeout=180s",
            label="central MQTT rollout",
            timeout_seconds=200,
        )

        _kubectl_patch_deployment(
            inventory,
            ue_deployment,
            render_edge_patch(scenario, lock=lock, core_address=core_address),
            label="srsUE Phase 3 sidecar patch",
        )
        _wait_rollout(inventory, ue_deployment, label="srsUE Phase 3 rollout")
        ue_pod = _discover_ue_pod(inventory, scenario.network_run_id)

        after_patch = verify_network_path(
            inventory=inventory,
            lock=lock,
            run_id=scenario.network_run_id,
            timeout_seconds=120,
        )
        if not after_patch.ready:
            raise Phase3Error("srsUE sidecar patch broke the accepted network path")

        _add_ue_route(inventory, ue_pod, core_address)
        _restart_edge_sidecar(inventory, ue_pod)
        time.sleep(3)
        tx_before = _interface_counter(inventory, ue_pod, "tun_srsue1", "tx_bytes")
        rx_before = _interface_counter(inventory, ue_pod, "tun_srsue1", "rx_bytes")

        edge_forward = _start_process(
            "edge MQTT port-forward",
            _ssh_tunnel_command(
                inventory,
                local_port=LOCAL_EDGE_FORWARD_PORT,
                remote_port=LOCAL_EDGE_FORWARD_PORT,
                remote_command=(
                    "KUBECONFIG=/etc/kubernetes/admin.conf kubectl port-forward "
                    f"-n {KUBERNETES_NAMESPACE} pod/{ue_pod} "
                    f"{LOCAL_EDGE_FORWARD_PORT}:1883 --address 127.0.0.1"
                ),
            ),
            cwd=repository_root,
            log_path=logs / "edge-port-forward.log",
        )
        processes.append(edge_forward)
        _wait_tcp("127.0.0.1", LOCAL_EDGE_FORWARD_PORT, timeout_seconds=30)

        central_forward = _start_process(
            "central MQTT port-forward",
            _ssh_tunnel_command(
                inventory,
                local_port=LOCAL_CENTRAL_FORWARD_PORT,
                remote_port=LOCAL_CENTRAL_FORWARD_PORT,
                remote_command=(
                    "KUBECONFIG=/etc/kubernetes/admin.conf kubectl port-forward "
                    f"-n {KUBERNETES_NAMESPACE} "
                    f"deployment/{resource_names['central_deployment']} "
                    f"{LOCAL_CENTRAL_FORWARD_PORT}:{CENTRAL_PORT} "
                    "--address 127.0.0.1"
                ),
            ),
            cwd=repository_root,
            log_path=logs / "central-port-forward.log",
        )
        processes.append(central_forward)
        _wait_tcp("127.0.0.1", LOCAL_CENTRAL_FORWARD_PORT, timeout_seconds=30)

        report("cooja: starting deterministic 10-sensor simulation...")
        cooja = _start_process(
            "Cooja",
            (
                str(contiki / "tools" / "cooja" / "gradlew"),
                "run",
                f"--args=--no-gui {csc}",
            ),
            cwd=contiki / "tools" / "cooja",
            log_path=logs / "cooja.log",
        )
        processes.append(cooja)
        _wait_tcp("127.0.0.1", scenario.serial_socket_port, timeout_seconds=180)
        extra_checks.append(
            Phase3Check(
                "cooja",
                True,
                "deterministic 10-sensor simulation exposed its serial socket",
            )
        )

        report("tunslip6: creating tun0...")
        tunslip = _start_process(
            "tunslip6",
            (
                "sudo",
                "-n",
                str(contiki / "tools" / "serial-io" / "tunslip6"),
                "-a",
                "127.0.0.1",
                "-p",
                str(scenario.serial_socket_port),
                "-t",
                "tun0",
                "fd00::1/64",
            ),
            cwd=repository_root,
            log_path=logs / "tunslip6.log",
        )
        processes.append(tunslip)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = _run(
                ("ip", "-j", "address", "show", "dev", "tun0"),
                timeout_seconds=5,
            )
            if result.returncode == 0 and "fd00::1" in result.stdout:
                break
            time.sleep(1)
        else:
            raise Phase3Error("tun0 did not become UP with fd00::1")
        extra_checks.append(
            Phase3Check(
                "rpl-border-router",
                True,
                "Cooja serial socket is bridged through tunslip6/tun0",
            )
        )

        proxy = CountedTcpProxy(
            listen_host="fd00::1",
            listen_port=1883,
            target_host="127.0.0.1",
            target_port=LOCAL_EDGE_FORWARD_PORT,
        )
        proxy.start()

        report("collector: waiting for all 10 sensor streams...")
        collection = collect_mqtt(
            scenario,
            host="127.0.0.1",
            port=LOCAL_CENTRAL_FORWARD_PORT,
            jsonl_path=jsonl_path,
            rejected_path=rejected_path,
            minimum_per_sensor=minimum_per_sensor,
            timeout_seconds=collection_seconds,
        )
        if not collection.completed:
            raise Phase3Error(
                "collector timed out after observing "
                f"{collection.sensors}/10 sensors and {collection.records} events"
            )
        report(f"collector: OK ({collection.records} events from 10 sensors)")

        proxy_snapshot = proxy.snapshot()
        if (
            proxy_snapshot.accepted_connections < scenario.sensor_count
            or proxy_snapshot.upstream_bytes <= 0
        ):
            raise Phase3Error("Cooja MQTT ingress was not proven through tun0")
        extra_checks.append(
            Phase3Check(
                "edge-mqtt",
                True,
                f"{proxy_snapshot.accepted_connections} sensor MQTT connections crossed the tun0 ingress",
            )
        )
        extra_checks.append(
            Phase3Check(
                "ue-binding",
                True,
                f"edge bridge is bound to accepted UE PDU address {scenario.pdu_address}",
            )
        )

        tx_after = _interface_counter(inventory, ue_pod, "tun_srsue1", "tx_bytes")
        rx_after = _interface_counter(inventory, ue_pod, "tun_srsue1", "rx_bytes")
        if tx_after <= tx_before:
            raise Phase3Error("tun_srsue1 TX counter did not increase during MQTT delivery")
        extra_checks.append(
            Phase3Check(
                "5g-egress",
                True,
                "tun_srsue1 counters increased "
                f"(tx +{tx_after - tx_before}, rx +{max(0, rx_after - rx_before)})",
            )
        )

        live_network = verify_network_path(
            inventory=inventory,
            lock=lock,
            run_id=scenario.network_run_id,
            timeout_seconds=120,
        )
        if not live_network.ready:
            raise Phase3Error("accepted UPF path was not valid after telemetry delivery")
        extra_checks.append(
            Phase3Check(
                "upf-path",
                True,
                "accepted slice-one UPF route remains path-proven",
            )
        )
        extra_checks.append(
            Phase3Check(
                "central-mqtt",
                True,
                "central broker delivered all 10 deterministic sensor streams",
            )
        )

        records = load_jsonl(jsonl_path, expected_run_id=scenario.run_id)
        write_parquet(records, parquet_path)
        data_evidence = build_offline_data_evidence(
            scenario=scenario,
            scenario_path=scenario_path,
            jsonl_path=jsonl_path,
            parquet_path=parquet_path,
            minimum_per_sensor=minimum_per_sensor,
            extra_checks=extra_checks,
        )
        if not data_evidence.ready:
            raise Phase3Error("Phase 3 data evidence is incomplete")

    except Exception as exc:
        failure = str(exc)
        report(f"Phase 3 failed: {failure}")
    finally:
        if proxy is not None:
            try:
                proxy.stop()
            except Exception as exc:
                if failure is None:
                    failure = f"Phase 3 ingress proxy cleanup failed: {exc}"
        for managed in reversed(processes):
            try:
                managed.stop()
            except Exception as exc:
                if failure is None:
                    failure = f"unable to stop {managed.name}: {exc}"
        cleanup_check = _cleanup_live_resources(
            inventory=inventory,
            lock=lock,
            scenario=scenario,
            ue_deployment=ue_deployment,
        )

    final = None
    if jsonl_path.is_file() and parquet_path.is_file():
        final = build_offline_data_evidence(
            scenario=scenario,
            scenario_path=scenario_path,
            jsonl_path=jsonl_path,
            parquet_path=parquet_path,
            minimum_per_sensor=minimum_per_sensor,
            extra_checks=(*extra_checks, cleanup_check),
        )
        save_phase3_evidence(final, evidence_path)

    ready = failure is None and final is not None and final.ready
    if failure is None and not cleanup_check.passed:
        failure = cleanup_check.detail
        ready = False

    _save_manifest(
        manifest_path,
        _render_manifest(
            scenario,
            status=(
                "iot-to-5g-path-proven"
                if ready
                else "failed"
                if failure is not None
                else "completed-unverified"
            ),
            scenario_path=scenario_path,
            failure=failure,
        ),
    )
    report("Phase 3: IOT-TO-5G PATH PROVEN" if ready else "Phase 3: NOT PROVEN")
    return Phase3RunResult(scenario.run_id, run_directory, evidence_path, ready)
