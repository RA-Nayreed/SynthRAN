#!/usr/bin/env python3
"""Executable contract for the shared #60 cross-RAN transition boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NETWORK = ROOT / "deployment/playbooks/network.yml"
ROLE = ROOT / "deployment/roles/5g/ran_transition/tasks/main.yml"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def text(path: Path) -> str:
    require(path.is_file(), f"missing required file: {path}")
    return path.read_text(encoding="utf-8")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def static_contract() -> None:
    network = text(NETWORK)
    role = text(ROLE)

    include = "name: 5g/ran_transition"
    require(network.count(include) == 1, "network.yml must invoke exactly one shared RAN transition owner")
    require(
        network.index(include) < network.index('- name: "Deploy the {{ core | upper }} core"'),
        "shared RAN transition must run before core/RAN workload deployment",
    )

    for needle in (
        "helm, list, --all-namespaces, --all, --output, json",
        "Remove only non-selected RAN releases",
        "--cascade",
        "foreground",
        "--wait",
        "Wait for incompatible RAN pods and RU attachments to disappear",
        "network-attachment-definitions.k8s.cni.cncf.io",
        "Prove exclusive pre-launch ownership for the selected RAN",
        "ran-transition.json",
        "srsran-gnb",
        "srsran-ue",
        "oai-gnb",
        "oai-du",
        "oai-cu",
        "oai-cu-up",
        "oai-cu-cp",
        "oai-flexric",
    ):
        require(needle in role, f"shared transition lost contract surface: {needle}")

    for forbidden in (
        "kubectl delete",
        "kubeadm reset",
        "helm upgrade",
        "helm install",
        "192.168.3.203",
        "192.168.235.105",
        "192.168.235.106",
    ):
        require(forbidden not in role, f"shared transition crossed its ownership boundary: {forbidden}")

    require(
        "if synthran_ran_transition_selected == 'oai'" in role,
        "shared transition no longer distinguishes selected/non-selected RAN ownership",
    )
    require(
        "item.name in synthran_ran_transition_incompatible_releases" in role,
        "release discovery is no longer fail-closed against the explicit incompatible set",
    )
    require(
        "item.metadata.name is match(synthran_ran_transition_incompatible_pod_pattern)" in role,
        "selected-node stale workload proof is missing",
    )


HELM_FAKE = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["SYNTHRAN_RAN_TRANSITION_FIXTURE"])


def load(name):
    path = root / name
    return json.loads(path.read_text(encoding="utf-8"))


def save(name, value):
    (root / name).write_text(json.dumps(value), encoding="utf-8")


args = sys.argv[1:]
if args[:2] == ["version", "--short"]:
    print("v3.22.0+gfixture")
    raise SystemExit(0)

if args and args[0] == "list":
    print(json.dumps(load("releases.json")))
    raise SystemExit(0)

if args and args[0] == "uninstall":
    name = args[1]
    try:
        namespace = args[args.index("--namespace") + 1]
    except (ValueError, IndexError):
        print("missing --namespace", file=sys.stderr)
        raise SystemExit(2)

    releases = load("releases.json")
    matched = [
        item for item in releases
        if item.get("name") == name
        and item.get("namespace") == namespace
        and item.get("status") != "uninstalled"
    ]
    if len(matched) != 1:
        print(f"release not uniquely active: {namespace}/{name}", file=sys.stderr)
        raise SystemExit(1)

    save(
        "releases.json",
        [
            item for item in releases
            if not (item.get("name") == name and item.get("namespace") == namespace)
        ],
    )

    pods = load("pods.json")
    kept = []
    for pod in pods.get("items", []):
        metadata = pod.get("metadata", {})
        labels = metadata.get("labels", {}) or {}
        owned = (
            metadata.get("namespace") == namespace
            and labels.get("app.kubernetes.io/instance") == name
        )
        if not owned:
            kept.append(pod)
    pods["items"] = kept
    save("pods.json", pods)

    nad_by_release = {
        "oai-gnb": "oai-gnb-ru",
        "oai-du": "oai-du-ru",
        "srsran-gnb": "ru-network",
    }
    nad_name = nad_by_release.get(name)
    if nad_name:
        nads = load("nads.json")
        nads["items"] = [
            item for item in nads.get("items", [])
            if not (
                item.get("metadata", {}).get("namespace") == namespace
                and item.get("metadata", {}).get("name") == nad_name
            )
        ]
        save("nads.json", nads)

    with (root / "uninstalls.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{namespace}/{name} {' '.join(args[2:])}\n")
    print(f"release {name} uninstalled")
    raise SystemExit(0)

print(f"unsupported fake helm invocation: {args!r}", file=sys.stderr)
raise SystemExit(2)
'''


KUBECTL_FAKE = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["SYNTHRAN_RAN_TRANSITION_FIXTURE"])
args = sys.argv[1:]


def load(name):
    return json.loads((root / name).read_text(encoding="utf-8"))


if len(args) >= 2 and args[0] == "get" and args[1] == "pods":
    data = load("pods.json")
    node = None
    if "--field-selector" in args:
        selector = args[args.index("--field-selector") + 1]
        if selector.startswith("spec.nodeName="):
            node = selector.split("=", 1)[1]
    if node:
        data["items"] = [
            item for item in data.get("items", [])
            if item.get("spec", {}).get("nodeName") == node
        ]
elif len(args) >= 2 and args[0] == "get" and args[1].startswith("network-attachment-definitions"):
    data = load("nads.json")
else:
    print(f"unsupported fake kubectl invocation: {args!r}", file=sys.stderr)
    raise SystemExit(2)

output = "json"
if "--output" in args:
    output = args[args.index("--output") + 1]
if output == "json":
    print(json.dumps(data))
elif output.startswith("jsonpath="):
    for item in data.get("items", []):
        print(item.get("metadata", {}).get("name", ""))
else:
    print(f"unsupported fake kubectl output: {output!r}", file=sys.stderr)
    raise SystemExit(2)
'''


PLAYBOOK = """---
- name: Exercise the production cross-RAN transition role
  hosts: ran_node
  gather_facts: false
  any_errors_fatal: true
  environment:
    PATH: "{{ fixture_bin }}:{{ lookup('env', 'PATH') }}"
    SYNTHRAN_RAN_TRANSITION_FIXTURE: "{{ fixture_state }}"
  vars:
    ran: "{{ fixture_ran }}"
    core: "{{ fixture_core }}"
    ran_node_name: ran-ci
    helm_version: "3.22.0"
    run_dir: "{{ fixture_run_dir }}"
    synthran_host_preparation: preserve
  roles:
    - role: 5g/ran_transition
"""


INVENTORY = """---
all:
  children:
    ran_node:
      hosts:
        ran-ci:
          ansible_connection: local
          ansible_python_interpreter: __PYTHON__
"""


def pod(namespace: str, name: str, release: str, node: str = "ran-ci", network: str = "") -> dict:
    annotations = {}
    if network:
        annotations["k8s.v1.cni.cncf.io/network-status"] = network
    return {
        "metadata": {
            "namespace": namespace,
            "name": name,
            "labels": {"app.kubernetes.io/instance": release},
            "annotations": annotations,
        },
        "spec": {"nodeName": node},
    }


def nad(namespace: str, name: str) -> dict:
    return {"metadata": {"namespace": namespace, "name": name}}


def prepare_fixture(
    root: Path,
    releases: list[dict],
    pods: list[dict],
    nads: list[dict],
) -> tuple[Path, Path, Path]:
    state = root / "state"
    fake_bin = root / "bin"
    run_dir = root / "result"
    state.mkdir()
    fake_bin.mkdir()
    run_dir.mkdir()
    write_json(state / "releases.json", releases)
    write_json(state / "pods.json", {"items": pods})
    write_json(state / "nads.json", {"items": nads})
    (state / "uninstalls.log").write_text("", encoding="utf-8")
    (fake_bin / "helm").write_text(HELM_FAKE, encoding="utf-8")
    (fake_bin / "kubectl").write_text(KUBECTL_FAKE, encoding="utf-8")
    make_executable(fake_bin / "helm")
    make_executable(fake_bin / "kubectl")
    return state, fake_bin, run_dir


def run_role(
    *,
    selected: str,
    core: str,
    releases: list[dict],
    pods: list[dict],
    nads: list[dict],
    expect_success: bool,
) -> tuple[dict, list[dict], dict, str]:
    ansible = shutil.which("ansible-playbook")
    require(ansible is not None, "ansible-playbook is required for the transition contract")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        roles = root / "roles"
        shutil.copytree(ROOT / "deployment/roles/5g/ran_transition", roles / "5g/ran_transition")
        shortened = roles / "5g/ran_transition/tasks/main.yml"
        source = shortened.read_text(encoding="utf-8")
        require(source.count("retries: 30") == 1, "production transition wait retry shape changed")
        require(source.count("delay: 2") == 1, "production transition wait delay shape changed")
        shortened.write_text(
            source.replace("retries: 30", "retries: 1").replace("delay: 2", "delay: 0"),
            encoding="utf-8",
        )

        state, fake_bin, run_dir = prepare_fixture(root, releases, pods, nads)
        inventory = root / "inventory.yml"
        inventory.write_text(
            INVENTORY.replace("__PYTHON__", sys.executable),
            encoding="utf-8",
        )
        playbook = root / "playbook.yml"
        playbook.write_text(PLAYBOOK, encoding="utf-8")

        env = os.environ.copy()
        env["ANSIBLE_ROLES_PATH"] = str(roles)
        env["ANSIBLE_NOCOLOR"] = "1"
        command = [
            ansible,
            "-i",
            str(inventory),
            str(playbook),
            "-e",
            f"fixture_ran={selected}",
            "-e",
            f"fixture_core={core}",
            "-e",
            f"fixture_state={state}",
            "-e",
            f"fixture_bin={fake_bin}",
            "-e",
            f"fixture_run_dir={run_dir}",
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if expect_success:
            require(result.returncode == 0, f"{selected} transition fixture failed:\n{result.stdout}")
            evidence_path = run_dir / "provenance/ran-transition.json"
            require(evidence_path.is_file(), "successful transition did not retain evidence")
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        else:
            require(result.returncode != 0, "orphan incompatible state was incorrectly accepted")
            evidence = {}

        final_releases = json.loads((state / "releases.json").read_text(encoding="utf-8"))
        final_pods = json.loads((state / "pods.json").read_text(encoding="utf-8"))
        log = (state / "uninstalls.log").read_text(encoding="utf-8")
        return evidence, final_releases, final_pods, log


def check_oai_to_srsran() -> None:
    evidence, releases, pods, log = run_role(
        selected="srsran",
        core="oai",
        releases=[
            {"name": "oai-5g-basic", "namespace": "oai", "status": "deployed"},
            {"name": "oai-gnb", "namespace": "legacy-oai", "status": "deployed"},
            {"name": "oai-flexric", "namespace": "legacy-oai", "status": "deployed"},
        ],
        pods=[
            pod(
                "legacy-oai",
                "oai-gnb-fixture",
                "oai-gnb",
                network='[{"name":"legacy-oai/oai-gnb-ru","interface":"ru"}]',
            ),
            pod("legacy-oai", "oai-flexric-fixture", "oai-flexric"),
        ],
        nads=[nad("legacy-oai", "oai-gnb-ru")],
        expect_success=True,
    )
    require({item["name"] for item in releases} == {"oai-5g-basic"}, "OAI core release was disturbed")
    require(pods["items"] == [], "old OAI RAN pods survived OAI -> srsRAN transition")
    require("legacy-oai/oai-gnb" in log and "legacy-oai/oai-flexric" in log, "old OAI releases were not removed")
    require("--cascade foreground" in log and "--wait" in log, "Helm foreground/wait semantics were lost")
    require(evidence["selected_ran"] == "srsran", "wrong selected RAN evidence")
    require(evidence["remaining_releases"] == [], "incompatible release survived evidence")
    require(evidence["remaining_pods"] == [], "incompatible pod survived evidence")
    require(evidence["remaining_ru_nads"] == [], "incompatible RU NAD survived evidence")


def check_srsran_to_oai() -> None:
    evidence, releases, pods, log = run_role(
        selected="oai",
        core="oai",
        releases=[
            {"name": "oai-5g-basic", "namespace": "oai", "status": "deployed"},
            {"name": "srsran-gnb", "namespace": "legacy-open5gs", "status": "deployed"},
            {"name": "srsran-ue", "namespace": "legacy-open5gs", "status": "deployed"},
        ],
        pods=[
            pod(
                "legacy-open5gs",
                "srsran-gnb-fixture",
                "srsran-gnb",
                network='[{"name":"legacy-open5gs/ru-network","interface":"ru1"}]',
            ),
            pod("legacy-open5gs", "srsran-ue-fixture", "srsran-ue"),
        ],
        nads=[nad("legacy-open5gs", "ru-network")],
        expect_success=True,
    )
    require({item["name"] for item in releases} == {"oai-5g-basic"}, "unrelated core release was disturbed")
    require(pods["items"] == [], "old srsRAN pods survived srsRAN -> OAI transition")
    require("legacy-open5gs/srsran-gnb" in log and "legacy-open5gs/srsran-ue" in log, "old srsRAN releases were not removed")
    require(evidence["selected_ran"] == "oai", "wrong selected RAN evidence")


def check_same_stack_is_not_stolen() -> None:
    evidence, releases, pods, log = run_role(
        selected="srsran",
        core="oai",
        releases=[
            {"name": "srsran-gnb", "namespace": "oai", "status": "deployed"},
            {"name": "srsran-ue", "namespace": "oai", "status": "deployed"},
        ],
        pods=[
            pod("oai", "srsran-gnb-fixture", "srsran-gnb"),
            pod("oai", "srsran-ue-fixture", "srsran-ue"),
        ],
        nads=[nad("oai", "ru-network")],
        expect_success=True,
    )
    require({item["name"] for item in releases} == {"srsran-gnb", "srsran-ue"}, "shared boundary stole selected srsRAN lifecycle")
    require(len(pods["items"]) == 2, "shared boundary deleted selected-stack pods")
    require(log == "", "same-stack rerun unexpectedly uninstalled a selected release")
    require(evidence["release_candidates_before"] == [], "selected-stack release was classified incompatible")


def check_orphan_fails_closed() -> None:
    _, releases, pods, log = run_role(
        selected="srsran",
        core="oai",
        releases=[],
        pods=[
            pod(
                "orphaned",
                "oai-gnb-orphan",
                "oai-gnb",
                network='[{"name":"orphaned/oai-gnb-ru","interface":"ru"}]',
            )
        ],
        nads=[nad("orphaned", "oai-gnb-ru")],
        expect_success=False,
    )
    require(releases == [], "orphan fixture unexpectedly gained Helm ownership")
    require(len(pods["items"]) == 1, "orphan workload was force-deleted instead of failing closed")
    require(log == "", "orphan fixture unexpectedly invoked Helm uninstall")


def main() -> None:
    static_contract()
    check_oai_to_srsran()
    check_srsran_to_oai()
    check_same_stack_is_not_stolen()
    check_orphan_fails_closed()
    print("shared cross-RAN transition contract OK")


if __name__ == "__main__":
    main()
