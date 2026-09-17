#!/usr/bin/env python3
"""Executable Sub 08 contract for core lifecycle/profile ownership."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REFERENCE_SHA = "6c9cb3a90c5cd88e1de3386c7eed76f25aa581d3"
OPEN5GS_SHA = "e53601e5209425867413d45d3d01ed9a1b696de7"
FREE5GC_SHA = "499ad3d6b0c0c8879f49edcc174f306ee72a4ff4"


class ContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def text(path: Path) -> str:
    require(path.is_file(), f"missing required file: {path}")
    return path.read_text(encoding="utf-8")


def git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def run_checked(argv: list[str]) -> None:
    subprocess.run(argv, check=True)


def check_reference(repo: Path, reference: Path) -> None:
    execution_ref = json.loads(
        text(repo / "third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json")
    )
    require(execution_ref["commit"] == REFERENCE_SHA, "execution reference SHA drifted")
    require(git_head(reference) == REFERENCE_SHA, "checked-out 5g-Ansible SHA is wrong")

    local_oai = text(repo / "deployment/roles/5g/oai/core/tasks/main.yml")
    materializer = text(
        repo / "deployment/roles/5g/oai/core/tasks/materialize_reference.yml"
    )
    upstream_oai = text(reference / "roles/5g/oai/core/tasks/main.yml")

    require("materialize_reference.yml" in local_oai, "OAI core does not materialize reference")
    require(
        "synthran_oai_core_reference_tasks" in local_oai,
        "OAI core does not include the reference-owned lifecycle",
    )
    for copied_marker in ("stop-cn", "start-cn", "oai-cn5g-fed"):
        require(copied_marker not in local_oai, f"OAI copied lifecycle marker retained: {copied_marker}")
    require("synthran.reference_checkout" in materializer, "OAI bypasses shared reference checkout")
    require("git\n      - -C" in materializer and "rev-parse" in materializer, "OAI reference SHA is not read back")
    require("ansible.builtin.git" not in materializer, "OAI introduced a second checkout engine")
    require("start-cn" in upstream_oai and "stop-cn" in upstream_oai, "pinned OAI lifecycle shape changed")


def check_open5gs(repo: Path, downstream: Path) -> None:
    require(git_head(downstream) == OPEN5GS_SHA, "checked-out Open5GS source SHA is wrong")

    defaults = text(repo / "deployment/roles/5g/open5gs/config/defaults/main.yml")
    config = text(repo / "deployment/roles/5g/open5gs/config/tasks/main.yml")
    deploy = text(repo / "deployment/roles/5g/open5gs/deploy/tasks/main.yml")

    require(OPEN5GS_SHA in defaults, "Open5GS source is not pinned to the reviewed SHA")
    require("network_profile_file" in config, "Open5GS does not load the effective profile")
    require(
        re.search(r"fiveg\.slices\s*\|\s*length\s*==\s*2", config) is not None,
        "Open5GS two-slot downstream constraint is not enforced",
    )

    forbidden = {
        "systemctl restart kubelet": "core role restarts kubelet",
        "rollout restart deployment/coredns": "core role owns CoreDNS",
        "kubectl patch networkattachmentdefinition": "core role live-patches NADs",
        "--force --grace-period=0": "core role force-deletes workloads",
        "failed_when: false": "Open5GS lifecycle suppresses a failure",
        "open5gs-node-patch.yaml": "dead Open5GS placement patch returned",
    }
    for marker, explanation in forbidden.items():
        require(marker not in deploy, explanation)

    for marker in (
        "synthran_topology.transport.endpoints.amf_ngap_ip",
        "synthran_topology.transport.bridges.core",
        "synthran_host_preparation == 'fresh'",
        "no_log: true",
    ):
        require(marker in deploy, f"Open5GS adapter lost required contract marker: {marker}")

    base_kustomization = text(downstream / "open5gs/kustomization.yaml")
    require(
        "r2labuser/open5gs-amf-patched:v2.7.0" in base_kustomization,
        "reviewed Open5GS AMF assertion-fix image is absent",
    )
    require((downstream / "open5gs/slices/slice1").is_dir(), "Open5GS slice1 slot missing")
    require((downstream / "open5gs/slices/slice2").is_dir(), "Open5GS slice2 slot missing")
    require(not (downstream / "open5gs/slices/slice3").exists(), "Open5GS downstream gained an unreviewed third slot")

    for rel, iface in (
        ("open5gs/common/amf/amf-deployment.yaml", "n3"),
        ("open5gs/slices/slice1/upf1/upf-deployment.yaml", "n3"),
    ):
        manifest = text(downstream / rel)
        require(
            f'"interface": "{iface}"' in manifest,
            f"pinned Open5GS manifest no longer owns its Multus interface name: {rel}",
        )


def check_free5gc(repo: Path, downstream: Path) -> None:
    require(git_head(downstream) == FREE5GC_SHA, "checked-out Free5GC source SHA is wrong")

    defaults = text(repo / "deployment/roles/5g/free5gc/config/defaults/main.yml")
    config = text(repo / "deployment/roles/5g/free5gc/config/tasks/main.yml")
    verify = text(repo / "deployment/roles/5g/free5gc/verify/tasks/main.yml")
    profile_check = text(repo / "deployment/roles/5g/free5gc/config/templates/profile-check.j2")

    require(FREE5GC_SHA in defaults, "Free5GC source is not pinned to the reviewed SHA")
    require(
        'free5gc_root: "{{ free5gc_repo_dest }}/charts/free5gc"' in defaults,
        "Free5GC root is not bound to its own checkout",
    )
    require("network_profile_file" in config, "Free5GC does not load the effective profile")
    require("coredns" not in config.lower(), "Free5GC adapter still mutates cluster-wide CoreDNS")
    require("Download yq" not in config, "Free5GC adapter still owns shared yq installation")

    for marker in ("failed_when: false", "ansible.builtin.debug", "WARNING:"):
        require(marker not in verify, f"Free5GC verifier retains non-fatal/private path: {marker}")
    require("/free5gc/add_subscribers.py" in verify, "Free5GC verifier does not use the exact baked script path")
    require("no_log: true" in verify, "Free5GC identity verification is not protected from logs")
    require(
        "authenticationData.authenticationSubscription" in verify,
        "Free5GC verifier does not prove exact subscriber cardinality",
    )

    for secret_marker in ("full_key", "profile.security.opc", "imsi-"):
        require(secret_marker not in profile_check, f"redacted Free5GC evidence contains {secret_marker}")

    dockerfile = text(downstream / "docker/free5gc/free5gc-dbpython/Dockerfile")
    require("WORKDIR /free5gc" in dockerfile, "Free5GC dbpython workdir changed")
    require("COPY add_subscribers.py add_subscribers.py" in dockerfile, "Free5GC dbpython script path changed")

    expected_source_markers = {
        "charts/free5gc/charts/free5gc-upf/templates/upf/upf-configmap.yaml": 'echo "1200 n6if" >> /etc/iproute2/rt_tables',
        "charts/free5gc/charts/free5gc-upf/templates/iupf1/iupf1-configmap.yaml": "iptables -A FORWARD -j ACCEPT",
        "charts/free5gc/charts/free5gc-upf/values.yaml": 'add: ["NET_ADMIN"]',
    }
    for rel, marker in expected_source_markers.items():
        require(marker in text(downstream / rel), f"retained Free5GC patch assumption drifted: {rel}")

    with tempfile.TemporaryDirectory(prefix="synthran-free5gc-contract-") as temp_dir:
        staged = Path(temp_dir) / "free5gc-helm"
        shutil.copytree(downstream, staged, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        patch_dir = repo / "deployment/roles/5g/free5gc/config/files"
        for patcher in (
            "patch_amf_n2_nad.py",
            "patch_iupf_n3_nad.py",
            "patch_nads.py",
            "patch_upf_wrapper.py",
        ):
            run_checked([sys.executable, str(patch_dir / patcher), str(staged)])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--open5gs-root", type=Path, required=True)
    parser.add_argument("--free5gc-root", type=Path, required=True)
    args = parser.parse_args()

    try:
        check_reference(args.repo_root.resolve(), args.reference_root.resolve())
        check_open5gs(args.repo_root.resolve(), args.open5gs_root.resolve())
        check_free5gc(args.repo_root.resolve(), args.free5gc_root.resolve())
    except (ContractError, subprocess.CalledProcessError) as exc:
        print(f"core lifecycle contract FAILED: {exc}", file=sys.stderr)
        return 1

    print("core lifecycle contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
