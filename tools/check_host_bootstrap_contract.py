#!/usr/bin/env python3
"""Static contract for issue #53 host/Kubernetes bootstrap ownership."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json"
ADAPTATIONS = ROOT / "third_party/sopnode-5g-ansible/HOST_BOOTSTRAP_ADAPTATIONS.json"


def fail(message: str) -> None:
    raise SystemExit(message)


def require(text: str, needle: str, context: str) -> None:
    if needle not in text:
        fail(f"{context}: missing required contract text: {needle!r}")


def forbid(text: str, needle: str, context: str) -> None:
    if needle in text:
        fail(f"{context}: forbidden legacy/bootstrap text remains: {needle!r}")


def _when_text(role: dict) -> str:
    value = role.get("when", "")
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True, type=Path)
    args = parser.parse_args()

    pin = json.loads(PIN.read_text(encoding="utf-8"))
    adaptations = json.loads(ADAPTATIONS.read_text(encoding="utf-8"))
    expected = pin["commit"]
    if adaptations["reference_commit"] != expected:
        fail("host bootstrap adaptation manifest does not match execution reference pin")

    actual = subprocess.run(
        ["git", "-C", str(args.reference), "rev-parse", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    if actual != expected:
        fail(f"reference checkout mismatch: expected {expected}, found {actual}")

    for role in adaptations["delegated_roles"]:
        local = ROOT / "deployment/roles" / role / "tasks/main.yml"
        upstream = args.reference / "roles" / role / "tasks/main.yml"
        if not local.is_file():
            fail(f"delegated role wrapper is missing: {role}")
        if not upstream.is_file():
            fail(f"delegated role missing from pinned reference: {role}")
        wrapper = local.read_text(encoding="utf-8")
        require(wrapper, "ansible.builtin.include_tasks", f"delegated wrapper {role}")
        require(
            wrapper,
            f"{{{{ synthran_reference_root }}}}/roles/{role}/tasks/main.yml",
            f"delegated wrapper {role}",
        )
        if len([line for line in wrapper.splitlines() if line.strip()]) > 4:
            fail(f"delegated role wrapper contains lifecycle logic instead of forwarding: {role}")

    all_vars = (ROOT / "deployment/group_vars/all/all.yml").read_text(encoding="utf-8")
    require(all_vars, "synthran_host_preparation", "all.yml")
    require(all_vars, "host_preparation", "all.yml")
    require(all_vars, "synthran_reference_root", "all.yml")
    require(all_vars, expected, "all.yml")

    site = (ROOT / "deployment/playbooks/site.yml").read_text(encoding="utf-8")
    provision_at = site.index("provision_nodes.yml")
    bootstrap_at = site.index("bootstrap_nodes.yml")
    network_at = site.index("network.yml")
    if not provision_at < bootstrap_at < network_at:
        fail("site.yml must run node validation, bootstrap, then transport/workloads")

    provision = (ROOT / "deployment/playbooks/provision_nodes.yml").read_text(encoding="utf-8")
    require(provision, "synthran_configured_storage", "provision_nodes.yml")
    require(provision, "Discover containerd storage only when inventory did not select one", "provision_nodes.yml")
    require(provision, "synthran_configured_storage | length == 0", "provision_nodes.yml")
    require(provision, "Use discovered storage only when inventory did not select one", "provision_nodes.yml")
    require(provision, "refusing to format", "provision_nodes.yml")
    require(provision, "mounted:%s:%s", "provision_nodes.yml")
    require(provision, "unmounted:%s", "provision_nodes.yml")
    require(provision, "host_preparation=preserve", "provision_nodes.yml")
    forbid(provision, "Record the selected containerd storage device", "provision_nodes.yml")

    pre_k8s = (ROOT / "deployment/roles/setup/pre_k8s/tasks/main.yml").read_text(encoding="utf-8")
    require(pre_k8s, "Find an existing mountpoint for the selected storage device", "pre_k8s")
    require(pre_k8s, "Bind already-mounted storage to the containerd data directory", "pre_k8s")
    require(pre_k8s, "Mount unmounted ext4 storage at the containerd data directory", "pre_k8s")
    require(pre_k8s, "SynthRAN will not format the device", "pre_k8s")
    require(pre_k8s, "Verify containerd storage is on a real filesystem", "pre_k8s")
    forbid(pre_k8s, "Configure kubelet storage eviction thresholds", "pre_k8s")
    forbid(pre_k8s, "kubeadm", "pre_k8s")

    bootstrap_path = ROOT / "deployment/playbooks/bootstrap_nodes.yml"
    bootstrap = bootstrap_path.read_text(encoding="utf-8")
    bootstrap_data = yaml.safe_load(bootstrap)
    destructive_roles = {
        "setup/common",
        "setup/netplan",
        "setup/containerd",
        "setup/pre_k8s",
        "setup/k8s/k8s_setup",
        "setup/optimization/cpu",
        "setup/ovs",
        "setup/k8s/cluster_create",
        "setup/k8s/cni_dhcp",
        "setup/k8s/cluster_join",
        "setup/k8s/add_taint",
        "setup/k8s/remove_taint",
        "setup/k8s/remove_cp_taint",
        "setup/cni",
        "setup/storage",
        "setup/k8s/k8s_cpu_tuning",
    }
    seen_roles = set()
    for play in bootstrap_data:
        for role_entry in play.get("roles", []):
            if isinstance(role_entry, str):
                role_name = role_entry
                role = {"role": role_name}
            else:
                role = role_entry
                role_name = role["role"]
            seen_roles.add(role_name)
            if role_name in destructive_roles and "synthran_host_preparation == 'fresh'" not in _when_text(role):
                fail(f"bootstrap_nodes.yml: mutating role lacks fresh-only guard: {role_name}")

    for role in destructive_roles:
        if role not in seen_roles and role not in {"setup/k8s/remove_taint"}:
            fail(f"bootstrap_nodes.yml: expected lifecycle role missing: {role}")

    require(bootstrap, "synthran_host_preparation == 'preserve'", "bootstrap_nodes.yml")
    require(bootstrap, "Verify preserved Kubernetes control plane is reachable", "bootstrap_nodes.yml")
    require(bootstrap, "Verify preserved CNI DHCP binary exists", "bootstrap_nodes.yml")
    forbid(bootstrap, "Move the kubeadm join command", "bootstrap_nodes.yml")
    forbid(bootstrap, ".kubeadm_join_command.txt", "bootstrap_nodes.yml")
    forbid(bootstrap, "setup/gre_tunnel", "bootstrap_nodes.yml")
    forbid(bootstrap, "name: 5g/", "bootstrap_nodes.yml")

    network = (ROOT / "deployment/playbooks/network.yml").read_text(encoding="utf-8")
    require(network, "setup/gre_tunnel", "network.yml")
    require(network, "5g/open5gs", "network.yml")
    forbid(network, "setup/k8s/cluster_create", "network.yml")
    forbid(network, "setup/common", "network.yml")
    forbid(network, "setup/pre_k8s", "network.yml")

    common = (ROOT / "deployment/roles/setup/common/tasks/main.yml").read_text(encoding="utf-8")
    forbid(common, "cni-dhcp.service", "common")

    cni = (ROOT / "deployment/roles/setup/k8s/cni_dhcp/tasks/main.yml").read_text(encoding="utf-8")
    binary_check = cni.index("Verify the CNI DHCP binary is installed")
    service_start = cni.index("Enable and start the CNI DHCP daemon")
    if binary_check >= service_start:
        fail("cni_dhcp must verify /opt/cni/bin/dhcp before service startup")
    require(cni, "synthran_cni_dhcp_binary.stat.executable", "cni_dhcp")

    cluster_create = (
        ROOT / "deployment/roles/setup/k8s/cluster_create/tasks/main.yml"
    ).read_text(encoding="utf-8")
    require(cluster_create, "Verify pre-k8s containerd storage binding", "cluster_create")
    require(cluster_create, "Configure kubelet storage eviction thresholds", "cluster_create")
    require(cluster_create, "{{ synthran_private_dir }}/kubeadm_join_command.txt", "cluster_create")
    require(cluster_create, "mode: '0600'", "cluster_create")
    require(cluster_create, "Save join command in private run directory", "cluster_create")
    forbid(cluster_create, "dest: .kubeadm_join_command.txt", "cluster_create")
    forbid(cluster_create, "/etc/kubernetes/config.conf", "cluster_create")
    forbid(cluster_create, "kubeproxy-config.yaml", "cluster_create")
    forbid(cluster_create, "Remount disk directly after reset", "cluster_create")
    forbid(cluster_create, "Unmount all stacked mounts on /var/lib/containerd after reset", "cluster_create")

    join = (ROOT / "deployment/roles/setup/k8s/cluster_join/tasks/main.yml").read_text(encoding="utf-8")
    require(join, "{{ synthran_private_dir }}/admin.conf", "cluster_join")
    require(join, "{{ synthran_private_dir }}/kubeadm_join_command.txt", "cluster_join")
    require(join, "mode: '0600'", "cluster_join")
    forbid(join, "/var/lib/kube-proxy/kubeproxy-config.yaml", "cluster_join")
    forbid(join, "/etc/kubernetes/config.conf", "cluster_join")

    join_material = "kubeadm_join_command.txt"
    allowed_join_paths = {
        ROOT / "deployment/roles/setup/k8s/cluster_create/tasks/main.yml",
        ROOT / "deployment/roles/setup/k8s/cluster_join/tasks/main.yml",
    }
    for path in (ROOT / "deployment").rglob("*.yml"):
        if join_material in path.read_text(encoding="utf-8") and path not in allowed_join_paths:
            fail(f"join material referenced outside private create/join roles: {path.relative_to(ROOT)}")

    reference_containerd = (
        args.reference / "roles/setup/containerd/tasks/main.yml"
    ).read_text(encoding="utf-8")
    for marker in (
        "Install containerd",
        "Switch snapshotter to overlayfs",
        "Wait for containerd socket",
    ):
        require(reference_containerd, marker, "reference containerd role")

    runtime = (ROOT / "synthran/runtime.py").read_text(encoding="utf-8")
    reference_checkout = (ROOT / "synthran/reference_checkout.py").read_text(encoding="utf-8")
    require(runtime, "ensure_execution_reference()", "runtime.py")
    require(reference_checkout, "rev-parse", "reference_checkout.py")
    require(reference_checkout, "status", "reference_checkout.py")

    print("issue #53 host/bootstrap ownership contract OK")


if __name__ == "__main__":
    main()
