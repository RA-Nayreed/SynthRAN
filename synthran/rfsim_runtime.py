"""Runtime reconciliation for the supported srsRAN RFSIM path.

Kubernetes readiness does not imply that the process-level RFSIM runtime is
active. The pinned upstream srsUE pod is intentionally kept alive while GNU
Radio and srsUE are started after deployment. Any srsUE pod rollout therefore
requires an explicit, ordered reconciliation before the accepted network path
can be reproven.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import json
import shlex
import subprocess
from typing import Any, Mapping, Sequence

from synthran.experiment import EXPECTED_PDU_NETWORK, ExperimentError
from synthran.fiveg_ansible import NetworkInventory
from synthran.live_preflight import CommandResult, LivePreflightError, ssh_command


KUBERNETES_NAMESPACE = "open5gs"
NETWORK_RUN_LABEL = "synthran.run/id"


@dataclass(frozen=True)
class RfsimRuntimeState:
    ue_pod: str
    gnb_pod: str
    gnb_deployment: str
    pdu_address: str


def _run(command: Sequence[str], *, timeout_seconds: int = 60) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExperimentError(f"required command was not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExperimentError("RFSIM runtime command timed out") from exc
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _remote_result(
    inventory: NetworkInventory,
    command: str,
    *,
    timeout_seconds: int = 60,
) -> CommandResult:
    try:
        remote = ssh_command(inventory.core_node, "sh", "-c", command)
    except LivePreflightError as exc:
        raise ExperimentError(str(exc)) from exc
    return _run(remote, timeout_seconds=timeout_seconds)


def _remote(
    inventory: NetworkInventory,
    command: str,
    *,
    label: str,
    timeout_seconds: int = 60,
) -> str:
    result = _remote_result(inventory, command, timeout_seconds=timeout_seconds)
    if result.returncode != 0:
        raise ExperimentError(f"{label} failed")
    return result.stdout


def _remote_json(
    inventory: NetworkInventory,
    command: str,
    *,
    label: str,
) -> Mapping[str, Any]:
    output = _remote(inventory, command, label=label)
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ExperimentError(f"{label} did not return JSON") from exc
    if not isinstance(value, dict):
        raise ExperimentError(f"{label} did not return one JSON object")
    return value


def _one_active_name(payload: Mapping[str, Any], *, label: str) -> str:
    items = payload.get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ExperimentError(f"{label} discovery returned malformed data")
    active = [
        item
        for item in items
        if not (
            isinstance(item.get("metadata"), dict)
            and item["metadata"].get("deletionTimestamp") is not None
        )
    ]
    if len(active) != 1:
        raise ExperimentError(
            f"expected exactly one active {label}, found {len(active)}"
        )
    metadata = active[0].get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str):
        raise ExperimentError(f"{label} metadata is malformed")
    return str(metadata["name"])


def _discover_pod(
    inventory: NetworkInventory,
    *,
    component: str,
    network_run_id: str | None = None,
) -> str:
    selector = f"app=srsran,component={component}"
    if network_run_id is not None:
        selector += f",{NETWORK_RUN_LABEL}={network_run_id}"
    payload = _remote_json(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl get pods "
        f"-n {KUBERNETES_NAMESPACE} -l {shlex.quote(selector)} -o json",
        label=f"active {component} pod discovery",
    )
    return _one_active_name(payload, label=f"{component} pod")


def _deployment_owner_for_pod(inventory: NetworkInventory, pod: str) -> str:
    payload = _remote_json(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl get pod "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(pod)} -o json",
        label="gNB pod owner discovery",
    )
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise ExperimentError("gNB pod metadata is malformed")
    owners = metadata.get("ownerReferences")
    if not isinstance(owners, list):
        raise ExperimentError("gNB pod has no ReplicaSet owner")
    replica_sets = [
        owner.get("name")
        for owner in owners
        if isinstance(owner, dict)
        and owner.get("kind") == "ReplicaSet"
        and isinstance(owner.get("name"), str)
    ]
    if len(replica_sets) != 1:
        raise ExperimentError("gNB pod does not have exactly one ReplicaSet owner")

    replica_set = str(replica_sets[0])
    replica_payload = _remote_json(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl get replicaset "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(replica_set)} -o json",
        label="gNB ReplicaSet owner discovery",
    )
    replica_metadata = replica_payload.get("metadata")
    if not isinstance(replica_metadata, dict):
        raise ExperimentError("gNB ReplicaSet metadata is malformed")
    rs_owners = replica_metadata.get("ownerReferences")
    if not isinstance(rs_owners, list):
        raise ExperimentError("gNB ReplicaSet has no Deployment owner")
    deployments = [
        owner.get("name")
        for owner in rs_owners
        if isinstance(owner, dict)
        and owner.get("kind") == "Deployment"
        and isinstance(owner.get("name"), str)
    ]
    if len(deployments) != 1:
        raise ExperimentError("gNB ReplicaSet does not have exactly one Deployment owner")
    return str(deployments[0])


def _wait_for_gnb_cell(inventory: NetworkInventory, pod: str) -> None:
    command = (
        "set -eu; "
        "for i in $(seq 1 60); do "
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(pod)} -c gnb-logs -- "
        "grep -q 'Cell was activated' /var/log/gnb.log >/dev/null 2>&1 && exit 0; "
        "sleep 2; done; exit 1"
    )
    _remote(
        inventory,
        command,
        label="fresh gNB cell readiness",
        timeout_seconds=130,
    )


def _wait_for_broker(inventory: NetworkInventory, pod: str) -> None:
    command = (
        "set -eu; "
        "for i in $(seq 1 30); do "
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(pod)} -c ue -- "
        "grep -q 'Press Enter to quit' /var/log/gnu_multi_ue.log >/dev/null 2>&1 && exit 0; "
        "sleep 2; done; exit 1"
    )
    _remote(
        inventory,
        command,
        label="GNU Radio broker readiness",
        timeout_seconds=70,
    )


def _wait_for_ue_tunnel(inventory: NetworkInventory, pod: str) -> None:
    command = (
        "set -eu; "
        "for i in $(seq 1 60); do "
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(pod)} -c ue -- "
        "/bin/sh -lc \"pgrep -af 'srsue .*ue_1\\.conf' >/dev/null "
        "&& ip link show tun_srsue1 >/dev/null 2>&1\" >/dev/null 2>&1 && exit 0; "
        "sleep 2; done; exit 1"
    )
    _remote(
        inventory,
        command,
        label="srsUE tunnel readiness",
        timeout_seconds=130,
    )


def _current_pdu_address(inventory: NetworkInventory, pod: str) -> str:
    output = _remote(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(pod)} -c ue -- "
        "ip -j address show dev tun_srsue1",
        label="current UE PDU address discovery",
    )
    try:
        interfaces = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ExperimentError("current UE PDU address discovery did not return JSON") from exc
    if not isinstance(interfaces, list):
        raise ExperimentError("current UE PDU address discovery returned malformed data")

    candidates: list[str] = []
    for interface in interfaces:
        if not isinstance(interface, dict):
            continue
        address_info = interface.get("addr_info")
        if not isinstance(address_info, list):
            continue
        for entry in address_info:
            if not isinstance(entry, dict) or entry.get("family") != "inet":
                continue
            local = entry.get("local")
            if not isinstance(local, str):
                continue
            try:
                address = ipaddress.ip_address(local)
            except ValueError:
                continue
            if address in EXPECTED_PDU_NETWORK:
                candidates.append(str(address))
    if len(candidates) != 1:
        raise ExperimentError(
            f"expected exactly one UE PDU address in {EXPECTED_PDU_NETWORK}, found {len(candidates)}"
        )
    return candidates[0]


def reconcile_rfsim_runtime(
    inventory: NetworkInventory,
    *,
    network_run_id: str,
) -> RfsimRuntimeState:
    """Restore the process-level RFSIM runtime after an srsUE pod rollout.

    The ordering is deliberate and mirrors the live-proven recovery contract:
    stop stale UE/broker state, restart the gNB while the broker is absent,
    wait for the fresh cell, start GNU Radio, start srsUE, wait for the tunnel,
    restore routes, and discover the newly assigned PDU address.
    """

    ue_pod = _discover_pod(
        inventory,
        component="ue",
        network_run_id=network_run_id,
    )
    old_gnb_pod = _discover_pod(
        inventory,
        component="gnb",
        network_run_id=network_run_id,
    )
    gnb_deployment = _deployment_owner_for_pod(inventory, old_gnb_pod)

    _remote(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(ue_pod)} -c ue -- /bin/sh -lc "
        + shlex.quote(
            "pkill -9 srsue 2>/dev/null || true; "
            "pkill -9 python3 2>/dev/null || true; "
            "tmux kill-session -t ran 2>/dev/null || true"
        ),
        label="stale RFSIM process cleanup",
    )

    restarted_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    patch = json.dumps(
        {
            "spec": {
                "template": {
                    "metadata": {
                        "labels": {NETWORK_RUN_LABEL: network_run_id},
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": restarted_at,
                        },
                    }
                }
            }
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    _remote(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl patch deployment "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(gnb_deployment)} "
        f"--type=merge -p {shlex.quote(patch)}",
        label="gNB runtime restart request",
    )
    _remote(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl rollout status deployment/"
        f"{shlex.quote(gnb_deployment)} -n {KUBERNETES_NAMESPACE} --timeout=180s",
        label="gNB runtime rollout",
        timeout_seconds=200,
    )

    gnb_pod = _discover_pod(
        inventory,
        component="gnb",
        network_run_id=network_run_id,
    )
    _wait_for_gnb_cell(inventory, gnb_pod)

    _remote(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(ue_pod)} -c ue -- "
        "/bin/sh -lc 'tmux new-session -d -s ran -n shell'",
        label="RFSIM tmux session creation",
    )
    _remote(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(ue_pod)} -c ue -- "
        "/bin/sh -lc "
        + shlex.quote('tmux new-window -t ran -n gnu "/srsran/config/start_gnu.sh 1"'),
        label="GNU Radio broker start",
    )
    _wait_for_broker(inventory, ue_pod)

    _remote(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(ue_pod)} -c ue -- "
        "/bin/sh -lc "
        + shlex.quote('tmux new-window -t ran -n ue1 "/srsran/config/start_ue.sh 1"'),
        label="srsUE start",
    )
    _wait_for_ue_tunnel(inventory, ue_pod)

    _remote(
        inventory,
        "KUBECONFIG=/etc/kubernetes/admin.conf kubectl exec "
        f"-n {KUBERNETES_NAMESPACE} {shlex.quote(ue_pod)} -c ue -- "
        "env UE_COUNT=1 /srsran/config/add_route.sh",
        label="srsUE route restoration",
    )
    pdu_address = _current_pdu_address(inventory, ue_pod)
    return RfsimRuntimeState(
        ue_pod=ue_pod,
        gnb_pod=gnb_pod,
        gnb_deployment=gnb_deployment,
        pdu_address=pdu_address,
    )
