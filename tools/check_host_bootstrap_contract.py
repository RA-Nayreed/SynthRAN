#!/usr/bin/env python3
"""Static contract for issue #53 host/Kubernetes bootstrap ownership."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

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
        if local.exists():
            fail(f"delegated role was copied back into SynthRAN: {role}")
        if not upstream.is_file():
            fail(f"delegated role missing from pinned reference: {role}")

    ansible_cfg = (ROOT / "ansible.cfg").read_text(encoding="utf-8")
    require(ansible_cfg, expected, "ansible.cfg")
    require(ansible_cfg, ".synthran/reference/sopnode-5g-ansible/", "ansible.cfg")

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
    require(provision, "host_preparation=preserve", "provision_nodes.yml")
    forbid(provision, "Record the selected containerd storage device", "provision_nodes.yml")

    bootstrap = (ROOT / "deployment/playbooks/bootstrap_nodes.yml").read_text(encoding="utf-8")
    for role in (
        "setup/common",
        "setup/netplan",
        "setup/containerd",
        "setup/pre_k8s",
        "setup/k8s/k8s_setup",
        "setup/k8s/cluster_create",
        "setup/k8s/cluster_join",
        "setup/k8s/add_taint",
        "setup/k8s/remove_taint",
        "setup/cni",
        "setup/storage",
        "setup/k8s/k8s_cpu_tuning",
    ):
        require(bootstrap, role, "bootstrap_nodes.yml")
    require(bootstrap, "synthran_host_preparation == 'fresh'", "bootstrap_nodes.yml")
    require(bootstrap, "synthran_host_preparation == 'preserve'", "bootstrap_nodes.yml")
    require(bootstrap, "Verify preserved Kubernetes control plane is reachable", "bootstrap_nodes.yml")
    require(bootstrap, "Verify preserved CNI DHCP binary exists", "bootstrap_nodes.yml")
    require(bootstrap, "{{ synthran_private_dir }}/kubeadm_join_command.txt", "bootstrap_nodes.yml")
    require(bootstrap, "- '0600'", "bootstrap_nodes.yml")
    forbid(bootstrap, "setup/gre_tunnel", "bootstrap_nodes.yml")
    forbid(bootstrap, "name: 5g/", "bootstrap_nodes.yml")

    network = (ROOT / "deployment/playbooks/network.yml").read_text(encoding="utf-8")
    require(network, "setup/gre_tunnel", "network.yml")
    require(network, "5g/open5gs", "network.yml")
    forbid(network, "setup/k8s/cluster_create", "network.yml")
    forbid(network, "setup/common", "network.yml")
    forbid(network, "setup/pre_k8s", "network.yml")

    cni = (ROOT / "deployment/roles/setup/k8s/cni_dhcp/tasks/main.yml").read_text(encoding="utf-8")
    binary_check = cni.index("Verify the CNI DHCP binary is installed")
    service_start = cni.index("Enable and start the CNI DHCP daemon")
    if binary_check >= service_start:
        fail("cni_dhcp must verify /opt/cni/bin/dhcp before service startup")
    require(cni, "synthran_cni_dhcp_binary.stat.executable", "cni_dhcp")

    join = (ROOT / "deployment/roles/setup/k8s/cluster_join/tasks/main.yml").read_text(encoding="utf-8")
    require(join, "{{ synthran_private_dir }}/admin.conf", "cluster_join")
    require(join, "{{ synthran_private_dir }}/kubeadm_join_command.txt", "cluster_join")
    require(join, "mode: '0600'", "cluster_join")
    forbid(join, "/var/lib/kube-proxy/kubeproxy-config.yaml", "cluster_join")
    forbid(join, "/etc/kubernetes/config.conf", "cluster_join")

    reference_containerd = (
        args.reference / "roles/setup/containerd/tasks/main.yml"
    ).read_text(encoding="utf-8")
    for marker in ("Install containerd", "Switch snapshotter to overlayfs", "Wait for containerd socket"):
        require(reference_containerd, marker, "reference containerd role")

    print("issue #53 host/bootstrap ownership contract OK")


if __name__ == "__main__":
    main()
