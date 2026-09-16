#!/usr/bin/env python3
"""Static contract for issue #53 host/Kubernetes bootstrap ownership."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json"
ADAPTATIONS = ROOT / "third_party/sopnode-5g-ansible/HOST_BOOTSTRAP_ADAPTATIONS.json"

LIFECYCLE_TAGS = {
    "synthran_fresh_only",
    "synthran_preserve_only",
    "synthran_shared_invariant",
}
PRESERVE_ALLOWED_MODULES = {
    "ansible.builtin.command",
    "ansible.builtin.stat",
    "ansible.builtin.assert",
}
SHARED_ALLOWED_MODULES = {
    "ansible.builtin.command",
    "ansible.builtin.set_fact",
    "ansible.builtin.copy",
}


def fail(message: str) -> None:
    raise SystemExit(message)


def require(text: str, needle: str, context: str) -> None:
    if needle not in text:
        fail(f"{context}: missing required contract text: {needle!r}")


def forbid(text: str, needle: str, context: str) -> None:
    if needle in text:
        fail(f"{context}: forbidden legacy/bootstrap text remains: {needle!r}")


def _when_text(entry: dict) -> str:
    value = entry.get("when", "")
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def _named_task(tasks: list[dict], name: str) -> dict:
    for task in tasks:
        if task.get("name") == name:
            return task
    fail(f"task missing from contract: {name}")
    raise AssertionError("unreachable")


def _task_tags(task: dict) -> set[str]:
    tags = task.get("tags", [])
    if isinstance(tags, str):
        return {tags}
    return {str(tag) for tag in tags}


def _task_module(task: dict) -> str:
    modules = [
        key
        for key in task
        if key.startswith("ansible.builtin.") or key.startswith("kubernetes.core.")
    ]
    if len(modules) != 1:
        fail(
            f"bootstrap task {task.get('name', '<unnamed>')!r} must expose exactly "
            f"one module for lifecycle auditing, found {modules}"
        )
    return modules[0]


def _command_argv(task: dict) -> list[str]:
    spec = task.get("ansible.builtin.command")
    if isinstance(spec, str):
        return shlex.split(spec)
    if isinstance(spec, dict):
        argv = spec.get("argv")
        if isinstance(argv, list):
            return [str(item) for item in argv]
        cmd = spec.get("cmd")
        if isinstance(cmd, str):
            return shlex.split(cmd)
    fail(f"cannot audit command shape for bootstrap task {task.get('name', '<unnamed>')!r}")
    raise AssertionError("unreachable")


def _require_read_only_command(task: dict, lifecycle: str) -> None:
    name = task.get("name", "<unnamed>")
    if task.get("changed_when") is not False:
        fail(f"{lifecycle} command must declare changed_when: false: {name}")

    argv = _command_argv(task)
    if not argv:
        fail(f"{lifecycle} command is empty: {name}")

    safe = False
    if argv[:2] == ["systemctl", "is-active"]:
        safe = True
    elif argv[0] == "findmnt":
        safe = True
    elif argv[0] == "kubectl" and "get" in argv[1:]:
        safe = True

    if not safe:
        fail(
            f"{lifecycle} command is not in the explicit read-only allowlist: "
            f"{name}: {argv}"
        )


def _validate_task_lifecycle(task: dict, section: str) -> None:
    name = task.get("name", "<unnamed>")
    lifecycle = _task_tags(task) & LIFECYCLE_TAGS
    if len(lifecycle) != 1:
        fail(
            f"bootstrap {section} task {name!r} must declare exactly one lifecycle "
            f"tag from {sorted(LIFECYCLE_TAGS)}, found {sorted(lifecycle)}"
        )

    lifecycle_tag = next(iter(lifecycle))
    when = _when_text(task)
    module = _task_module(task)
    serialized = json.dumps(task, sort_keys=True)

    if lifecycle_tag == "synthran_fresh_only":
        if "synthran_host_preparation == 'fresh'" not in when:
            fail(f"fresh-only bootstrap task lacks fresh guard: {name}")
        return

    if lifecycle_tag == "synthran_preserve_only":
        if "synthran_host_preparation == 'preserve'" not in when:
            fail(f"preserve-only bootstrap task lacks preserve guard: {name}")
        if module not in PRESERVE_ALLOWED_MODULES:
            fail(f"preserve bootstrap task uses mutating/unapproved module {module}: {name}")
        if module == "ansible.builtin.command":
            _require_read_only_command(task, "preserve")
        for forbidden in ("yq", "helm", "get_url", "apt", "package", "pip", "unarchive"):
            if forbidden in serialized.lower():
                fail(f"preserve bootstrap task references fresh/deployment tooling {forbidden!r}: {name}")
        return

    if "synthran_host_preparation" in when:
        fail(f"shared bootstrap invariant must not branch on host_preparation: {name}")
    if module not in SHARED_ALLOWED_MODULES:
        fail(f"shared bootstrap invariant uses unapproved module {module}: {name}")
    if module == "ansible.builtin.command":
        _require_read_only_command(task, "shared")
    if module == "ansible.builtin.copy":
        if task.get("delegate_to") != "localhost" or task.get("become") is not False:
            fail(f"shared copy is only allowed for controller-local evidence: {name}")


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
    require(all_vars, "setup/deployment_runtime", "all.yml")
    forbid(all_vars, "yq_url", "all.yml")

    site = (ROOT / "deployment/playbooks/site.yml").read_text(encoding="utf-8")
    provision_at = site.index("provision_nodes.yml")
    bootstrap_at = site.index("bootstrap_nodes.yml")
    runtime_at = site.index("deployment_runtime.yml")
    network_at = site.index("network.yml")
    provenance_at = site.index("provenance.yml")
    if not provision_at < bootstrap_at < runtime_at < network_at < provenance_at:
        fail(
            "site.yml must run node validation, bootstrap verification/mutation, "
            "deployment runtime, transport/workloads, then provenance"
        )

    runtime_playbook = (
        ROOT / "deployment/playbooks/deployment_runtime.yml"
    ).read_text(encoding="utf-8")
    require(runtime_playbook, "hosts: sopnodes", "deployment_runtime.yml")
    require(runtime_playbook, "role: setup/deployment_runtime", "deployment_runtime.yml")

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
    require(pre_k8s, "storage binding only", "pre_k8s")
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
        "setup/deployment_runtime",
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
        for section in ("pre_tasks", "tasks", "post_tasks"):
            for task in play.get(section, []):
                _validate_task_lifecycle(task, section)

    for role in destructive_roles:
        if role not in seen_roles:
            fail(f"bootstrap_nodes.yml: expected lifecycle role missing: {role}")

    require(bootstrap, "synthran_host_preparation == 'preserve'", "bootstrap_nodes.yml")
    require(bootstrap, "Verify preserved Kubernetes control plane is reachable", "bootstrap_nodes.yml")
    require(bootstrap, "Verify preserved CNI DHCP binary exists", "bootstrap_nodes.yml")
    require(bootstrap, "Write shareable bootstrap evidence", "bootstrap_nodes.yml")
    require(bootstrap, "bootstrap-evidence.json", "bootstrap_nodes.yml")
    require(bootstrap, "containerd_mount", "bootstrap_nodes.yml")
    require(bootstrap, "cni_dhcp", "bootstrap_nodes.yml")
    require(bootstrap, "cluster_nodes", "bootstrap_nodes.yml")
    require(bootstrap, "role: setup/deployment_runtime", "bootstrap_nodes.yml")
    forbid(bootstrap, "Read back the installed yq version", "bootstrap_nodes.yml")
    forbid(bootstrap, "Install the checksum-verified shared yq binary", "bootstrap_nodes.yml")
    forbid(bootstrap, "Move the kubeadm join command", "bootstrap_nodes.yml")
    forbid(bootstrap, ".kubeadm_join_command.txt", "bootstrap_nodes.yml")
    forbid(bootstrap, "setup/gre_tunnel", "bootstrap_nodes.yml")
    forbid(bootstrap, "name: 5g/", "bootstrap_nodes.yml")

    deployment_runtime = (
        ROOT / "deployment/roles/setup/deployment_runtime/tasks/main.yml"
    ).read_text(encoding="utf-8")
    for marker in (
        "kubernetes_python_version",
        "helm_sha256",
        "yq_sha256",
        "Install the checksum-pinned yq release",
        "Require the checksum-pinned Helm release",
        "Require the checksum-pinned yq release",
        "Use the shared Kubernetes-enabled Python runtime",
    ):
        require(deployment_runtime, marker, "setup/deployment_runtime")
    forbid(deployment_runtime, "yq_url", "setup/deployment_runtime")

    k8s_setup = (ROOT / "deployment/roles/setup/k8s/k8s_setup/tasks/main.yml").read_text(encoding="utf-8")
    forbid(k8s_setup, "helm_version", "k8s_setup")
    forbid(k8s_setup, "yq_version", "k8s_setup")
    forbid(k8s_setup, "kubernetes_python_version", "k8s_setup")

    network = (ROOT / "deployment/playbooks/network.yml").read_text(encoding="utf-8")
    require(network, "setup/gre_tunnel", "network.yml")
    require(network, "5g/open5gs", "network.yml")
    forbid(network, "setup/deployment_runtime", "network.yml")
    forbid(network, "setup/k8s/cluster_create", "network.yml")
    forbid(network, "setup/common", "network.yml")
    forbid(network, "setup/pre_k8s", "network.yml")

    for relative in (
        "deployment/roles/5g/free5gc/config/tasks/main.yml",
        "deployment/roles/5g/free5gc/deploy/tasks/main.yml",
        "deployment/roles/5g/ueransim/config/tasks/main.yml",
        "deployment/roles/5g/ueransim/config/tasks/config_open5gs.yml",
    ):
        backend = (ROOT / relative).read_text(encoding="utf-8")
        forbid(backend, "Download yq binary", relative)
        forbid(backend, "yq_url", relative)

    common = (ROOT / "deployment/roles/setup/common/tasks/main.yml").read_text(encoding="utf-8")
    forbid(common, "cni-dhcp.service", "common")

    cni = (ROOT / "deployment/roles/setup/k8s/cni_dhcp/tasks/main.yml").read_text(encoding="utf-8")
    binary_check = cni.index("Verify the CNI DHCP binary is installed")
    service_start = cni.index("Enable and start the CNI DHCP daemon")
    if binary_check >= service_start:
        fail("cni_dhcp must verify /opt/cni/bin/dhcp before service startup")
    require(cni, "synthran_cni_dhcp_binary.stat.executable", "cni_dhcp")

    cluster_create_path = ROOT / "deployment/roles/setup/k8s/cluster_create/tasks/main.yml"
    cluster_create = cluster_create_path.read_text(encoding="utf-8")
    cluster_create_tasks = yaml.safe_load(cluster_create)
    require(cluster_create, "Verify pre-k8s containerd storage binding", "cluster_create")
    require(cluster_create, "Configure kubelet storage eviction thresholds", "cluster_create")
    require(cluster_create, "{{ synthran_private_dir }}/kubeadm_join_command.txt", "cluster_create")
    forbid(cluster_create, "dest: .kubeadm_join_command.txt", "cluster_create")
    forbid(cluster_create, "/etc/kubernetes/config.conf", "cluster_create")
    forbid(cluster_create, "kubeproxy-config.yaml", "cluster_create")
    forbid(cluster_create, "Remount disk directly after reset", "cluster_create")
    forbid(cluster_create, "Unmount all stacked mounts on /var/lib/containerd after reset", "cluster_create")

    generate_join = _named_task(cluster_create_tasks, "Generate join command")
    save_join = _named_task(cluster_create_tasks, "Save join command in private run directory")
    if generate_join.get("no_log") is not True:
        fail("cluster_create: join-token generation must use no_log")
    if save_join.get("no_log") is not True:
        fail("cluster_create: join-token persistence must use no_log")
    copy_spec = save_join.get("ansible.builtin.copy") or {}
    if copy_spec.get("dest") != "{{ synthran_private_dir }}/kubeadm_join_command.txt":
        fail("cluster_create: join token must be born inside synthran_private_dir")
    if str(copy_spec.get("mode")) != "0600":
        fail("cluster_create: private join token must use mode 0600")

    join = (ROOT / "deployment/roles/setup/k8s/cluster_join/tasks/main.yml").read_text(encoding="utf-8")
    require(join, "{{ synthran_private_dir }}/admin.conf", "cluster_join")
    require(join, "{{ synthran_private_dir }}/kubeadm_join_command.txt", "cluster_join")
    require(join, "mode: '0600'", "cluster_join")
    forbid(join, "/var/lib/kube-proxy/kubeproxy-config.yaml", "cluster_join")
    forbid(join, "/etc/kubernetes/config.conf", "cluster_join")

    join_material = "kubeadm_join_command.txt"
    allowed_join_paths = {
        cluster_create_path,
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

    provenance = (ROOT / "deployment/playbooks/provenance.yml").read_text(encoding="utf-8")
    require(provenance, "Require deployment tooling to match the pinned runtime baseline", "provenance.yml")
    require(provenance, "Require the pinned Kubernetes host baseline after fresh preparation", "provenance.yml")
    require(provenance, "when: synthran_host_preparation == 'fresh'", "provenance.yml")
    require(provenance, "'host_preparation': synthran_host_preparation", "provenance.yml")
    forbid(provenance, "Refusing activation/reuse until the host is provisioned by this baseline", "provenance.yml")

    runtime = (ROOT / "synthran/runtime.py").read_text(encoding="utf-8")
    reference_checkout = (ROOT / "synthran/reference_checkout.py").read_text(encoding="utf-8")
    require(runtime, "ensure_execution_reference()", "runtime.py")
    require(reference_checkout, "rev-parse", "reference_checkout.py")
    require(reference_checkout, "status", "reference_checkout.py")

    print("issue #53 host/bootstrap ownership contract OK")


if __name__ == "__main__":
    main()
