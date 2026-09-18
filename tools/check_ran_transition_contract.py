#!/usr/bin/env python3
"""Executable contract for the shared #60 physical cross-RAN transition."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
NETWORK = ROOT / "deployment/playbooks/network.yml"
DEFAULTS = ROOT / "deployment/roles/5g/ran_transition/defaults/main.yml"
ROLE = ROOT / "deployment/roles/5g/ran_transition/tasks/main.yml"
OAI_RAN = ROOT / "deployment/roles/5g/oai/ran/tasks/main.yml"
SRSRAN_GNB = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/deploy_gnb.yml"


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
    defaults_text = text(DEFAULTS)
    defaults = yaml.safe_load(defaults_text)

    require(
        network.count("name: 5g/ran_transition") == 1,
        "network.yml must invoke exactly one shared RAN transition owner",
    )
    transition_index = network.index("name: 5g/ran_transition")
    require(
        transition_index > network.index("name: 5g/oai/core"),
        "transition must run after optional OAI core deployment",
    )
    require(
        transition_index < network.index("name: 5g/oai/ran"),
        "transition must run before OAI RAN lifecycle",
    )
    require(
        transition_index < network.index("name: 5g/srsRAN/config"),
        "transition must run before srsRAN configuration/lifecycle",
    )
    for gate in (
        "platform | string | trim | lower == 'r2lab'",
        "rru | string | trim | lower in ['n300', 'n320']",
        "ran | string | trim | lower in ['oai', 'srsran']",
    ):
        require(gate in network, f"network transition lost physical scope gate: {gate}")

    catalog = defaults["synthran_ran_transition_catalog"]
    require(
        [item["release"] for item in catalog["oai"]]
        == ["oai-gnb", "oai-du", "oai-cu", "oai-cu-up", "oai-cu-cp"],
        "OAI transition catalog drifted from the known RAN release family",
    )
    require(
        [item["release"] for item in catalog["srsran"]] == ["srsran-gnb"],
        "srsRAN transition catalog must own only the physical gNB release",
    )
    require(catalog["oai"][0]["ru_nad"] == "oai-gnb-ru", "OAI gNB RU NAD changed")
    require(catalog["oai"][1]["ru_nad"] == "oai-du-ru", "OAI DU RU NAD changed")
    require(catalog["srsran"][0]["ru_nad"] == "ru-network", "srsRAN RU NAD changed")

    for forbidden in ("oai-flexric", "oai-nr-ue", "srsran-ue"):
        require(
            forbidden not in defaults_text,
            f"transition expanded outside RAN ownership into {forbidden}",
        )

    for needle in (
        "--namespace",
        "--cascade",
        "foreground",
        "--wait",
        "--no-hooks",
        "Remove a known orphaned incompatible Deployment",
        "Remove any known orphaned incompatible pods and wait for CNI teardown",
        "Remove an incompatible RU NAD only after its pods are gone",
        "Prove exclusive pre-launch ownership for the selected RAN",
        "ran-transition.json",
    ):
        require(needle in role, f"transition lost required contract surface: {needle}")

    require("--all-namespaces" not in role, "transition must not touch unrelated namespaces")
    require("!= 'uninstalled'" in role, "Helm history is no longer distinguished from live ownership")

    for forbidden in (
        "kubeadm reset",
        "helm upgrade",
        "helm install",
        "192.168.3.203",
        "192.168.235.105",
        "192.168.235.106",
    ):
        require(forbidden not in role, f"transition crossed its ownership boundary: {forbidden}")

    require("srsran-gnb" not in text(OAI_RAN), "OAI backend reintroduced srsRAN cleanup")
    for marker in ("oai-gnb", "oai-du", "oai-cu"):
        require(marker not in text(SRSRAN_GNB), f"srsRAN backend reintroduced OAI cleanup: {marker}")


HELM = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["SYNTHRAN_RAN_TRANSITION_FIXTURE"])


def load(name):
    return json.loads((root / name).read_text(encoding="utf-8"))


def save(name, value):
    (root / name).write_text(json.dumps(value), encoding="utf-8")


def ns_arg(args):
    return args[args.index("--namespace") + 1]


def selector_for(release):
    if release == "srsran-gnb":
        return {"app": "srsran", "component": "gnb"}
    return {"app.kubernetes.io/instance": release}


args = sys.argv[1:]
if args[:2] == ["version", "--short"]:
    print("v3.22.0+gfixture")
    raise SystemExit(0)

if args and args[0] == "list":
    namespace = ns_arg(args)
    print(json.dumps([
        item for item in load("releases.json")
        if item.get("namespace") == namespace
    ]))
    raise SystemExit(0)

if args and args[0] == "uninstall":
    release = args[1]
    namespace = ns_arg(args)
    releases = load("releases.json")
    matches = [
        item for item in releases
        if item.get("name") == release
        and item.get("namespace") == namespace
        and item.get("status") != "uninstalled"
    ]
    if len(matches) != 1:
        print(f"release not uniquely active: {namespace}/{release}", file=sys.stderr)
        raise SystemExit(1)

    save("releases.json", [
        item for item in releases
        if not (
            item.get("name") == release
            and item.get("namespace") == namespace
            and item.get("status") != "uninstalled"
        )
    ])

    deployments = load("deployments.json")
    deployments["items"] = [
        item for item in deployments["items"]
        if not (
            item["metadata"]["namespace"] == namespace
            and item["metadata"]["name"] == release
        )
    ]
    save("deployments.json", deployments)

    wanted = selector_for(release)
    pods = load("pods.json")
    pods["items"] = [
        item for item in pods["items"]
        if not (
            item["metadata"]["namespace"] == namespace
            and all(item["metadata"].get("labels", {}).get(k) == v for k, v in wanted.items())
        )
    ]
    save("pods.json", pods)

    nad_map = {
        "oai-gnb": "oai-gnb-ru",
        "oai-du": "oai-du-ru",
        "srsran-gnb": "ru-network",
    }
    if release in nad_map:
        nads = load("nads.json")
        nads["items"] = [
            item for item in nads["items"]
            if not (
                item["metadata"]["namespace"] == namespace
                and item["metadata"]["name"] == nad_map[release]
            )
        ]
        save("nads.json", nads)

    with (root / "uninstalls.log").open("a", encoding="utf-8") as handle:
        handle.write(" ".join(args) + "\n")
    print(f"release {release} uninstalled")
    raise SystemExit(0)

print(f"unsupported fake helm invocation: {args!r}", file=sys.stderr)
raise SystemExit(2)
'''


KUBECTL = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["SYNTHRAN_RAN_TRANSITION_FIXTURE"])
args = sys.argv[1:]


def load(name):
    return json.loads((root / name).read_text(encoding="utf-8"))


def save(name, value):
    (root / name).write_text(json.dumps(value), encoding="utf-8")


def namespace():
    if "--namespace" in args:
        return args[args.index("--namespace") + 1]
    return None


def selector():
    if "--selector" not in args:
        return {}
    raw = args[args.index("--selector") + 1]
    return dict(part.split("=", 1) for part in raw.split(",") if "=" in part)


def labels_match(item, wanted):
    labels = item.get("metadata", {}).get("labels", {}) or {}
    return all(labels.get(k) == v for k, v in wanted.items())


if args[:2] == ["get", "namespace"]:
    name = args[2]
    if name not in load("namespaces.json"):
        raise SystemExit(1)
    print(f"namespace/{name}")
    raise SystemExit(0)

if args[:2] == ["get", "pods"]:
    ns = namespace()
    wanted = selector()
    items = [
        item for item in load("pods.json")["items"]
        if item["metadata"]["namespace"] == ns and labels_match(item, wanted)
    ]
    print("\n".join(f"pod/{item['metadata']['name']}" for item in items))
    raise SystemExit(0)

if args[:2] == ["get", "deployments"]:
    ns = namespace()
    data = load("deployments.json")
    data["items"] = [item for item in data["items"] if item["metadata"]["namespace"] == ns]
    print(json.dumps(data))
    raise SystemExit(0)

if args[:2] == ["get", "network-attachment-definitions.k8s.cni.cncf.io"]:
    ns = namespace()
    data = load("nads.json")
    data["items"] = [item for item in data["items"] if item["metadata"]["namespace"] == ns]
    print(json.dumps(data))
    raise SystemExit(0)

if args[:2] == ["delete", "deployment"]:
    name = args[2]
    ns = namespace()
    data = load("deployments.json")
    data["items"] = [
        item for item in data["items"]
        if not (item["metadata"]["namespace"] == ns and item["metadata"]["name"] == name)
    ]
    save("deployments.json", data)
    print(f"deployment.apps/{name} deleted")
    raise SystemExit(0)

if args[:2] == ["delete", "pods"]:
    ns = namespace()
    wanted = selector()
    data = load("pods.json")
    data["items"] = [
        item for item in data["items"]
        if not (item["metadata"]["namespace"] == ns and labels_match(item, wanted))
    ]
    save("pods.json", data)
    print("pod deleted")
    raise SystemExit(0)

if args[:2] == ["delete", "network-attachment-definitions.k8s.cni.cncf.io"]:
    name = args[2]
    ns = namespace()
    data = load("nads.json")
    data["items"] = [
        item for item in data["items"]
        if not (item["metadata"]["namespace"] == ns and item["metadata"]["name"] == name)
    ]
    save("nads.json", data)
    print(f"network-attachment-definition.k8s.cni.cncf.io/{name} deleted")
    raise SystemExit(0)

print(f"unsupported fake kubectl invocation: {args!r}", file=sys.stderr)
raise SystemExit(2)
'''


PLAYBOOK = """---
- name: Exercise production cross-RAN transition
  hosts: ran_node
  gather_facts: false
  environment:
    PATH: "{{ fixture_bin }}:{{ lookup('env', 'PATH') }}"
    SYNTHRAN_RAN_TRANSITION_FIXTURE: "{{ fixture_state }}"
  vars:
    platform: r2lab
    rru: n320
    ran: "{{ fixture_ran }}"
    core: oai
    ran_node_name: ran-ci
    helm_version: "3.22.0"
    run_dir: "{{ fixture_run }}"
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


def deployment(namespace: str, name: str) -> dict:
    return {"metadata": {"namespace": namespace, "name": name}}


def pod(namespace: str, name: str, labels: dict[str, str]) -> dict:
    return {"metadata": {"namespace": namespace, "name": name, "labels": labels}}


def nad(namespace: str, name: str) -> dict:
    return {"metadata": {"namespace": namespace, "name": name}}


def run_fixture(selected: str, state: dict[str, object]) -> tuple[dict, dict[str, object], str]:
    ansible = shutil.which("ansible-playbook")
    require(ansible is not None, "ansible-playbook is required for transition contract")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copytree(
            ROOT / "deployment/roles/5g/ran_transition",
            root / "roles/5g/ran_transition",
        )
        fake_bin = root / "bin"
        fake_bin.mkdir(parents=True)
        (fake_bin / "helm").write_text(HELM, encoding="utf-8")
        (fake_bin / "kubectl").write_text(KUBECTL, encoding="utf-8")
        make_executable(fake_bin / "helm")
        make_executable(fake_bin / "kubectl")

        state_dir = root / "state"
        state_dir.mkdir()
        for name in ("namespaces", "releases", "deployments", "pods", "nads"):
            write_json(state_dir / f"{name}.json", state[name])
        (state_dir / "uninstalls.log").write_text("", encoding="utf-8")

        run_dir = root / "run"
        run_dir.mkdir()
        inventory = root / "inventory.yml"
        inventory.write_text(INVENTORY.replace("__PYTHON__", sys.executable), encoding="utf-8")
        playbook = root / "playbook.yml"
        playbook.write_text(PLAYBOOK, encoding="utf-8")

        env = os.environ.copy()
        env["ANSIBLE_ROLES_PATH"] = str(root / "roles")
        env["ANSIBLE_NOCOLOR"] = "1"
        result = subprocess.run(
            [
                ansible,
                "-i",
                str(inventory),
                str(playbook),
                "-e",
                f"fixture_ran={selected}",
                "-e",
                f"fixture_state={state_dir}",
                "-e",
                f"fixture_bin={fake_bin}",
                "-e",
                f"fixture_run={run_dir}",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        require(result.returncode == 0, f"{selected} transition fixture failed:\n{result.stdout}")

        evidence = json.loads(
            (run_dir / "provenance/ran-transition.json").read_text(encoding="utf-8")
        )
        final = {
            name: json.loads((state_dir / f"{name}.json").read_text(encoding="utf-8"))
            for name in ("namespaces", "releases", "deployments", "pods", "nads")
        }
        log = (state_dir / "uninstalls.log").read_text(encoding="utf-8")
        return evidence, final, log


def base_state() -> dict[str, object]:
    return {
        "namespaces": ["oai", "other"],
        "releases": [],
        "deployments": {"items": []},
        "pods": {"items": []},
        "nads": {"items": []},
    }


def check_oai_to_srsran() -> None:
    state = base_state()
    state["releases"] = [
        {"name": "oai-5g-basic", "namespace": "oai", "status": "deployed"},
        {"name": "oai-gnb", "namespace": "oai", "status": "deployed"},
        {"name": "oai-du", "namespace": "oai", "status": "uninstalled"},
        {"name": "srsran-gnb", "namespace": "oai", "status": "deployed"},
        {"name": "oai-flexric", "namespace": "oai", "status": "deployed"},
        {"name": "oai-nr-ue", "namespace": "oai", "status": "deployed"},
        {"name": "oai-gnb", "namespace": "other", "status": "deployed"},
    ]
    state["deployments"]["items"] = [
        deployment("oai", "oai-gnb"),
        deployment("oai", "srsran-gnb"),
        deployment("other", "oai-gnb"),
    ]
    state["pods"]["items"] = [
        pod("oai", "oai-gnb-old", {"app.kubernetes.io/instance": "oai-gnb"}),
        pod("oai", "srsran-gnb-selected", {"app": "srsran", "component": "gnb"}),
        pod("oai", "oai-flexric", {"app.kubernetes.io/instance": "oai-flexric"}),
        pod("oai", "oai-nr-ue", {"app.kubernetes.io/instance": "oai-nr-ue"}),
        pod("other", "oai-gnb-other", {"app.kubernetes.io/instance": "oai-gnb"}),
    ]
    state["nads"]["items"] = [
        nad("oai", "oai-gnb-ru"),
        nad("oai", "ru-network"),
        nad("other", "oai-gnb-ru"),
    ]

    evidence, final, log = run_fixture("srsran", state)
    release_keys = {(item["namespace"], item["name"], item["status"]) for item in final["releases"]}
    require(("oai", "oai-gnb", "deployed") not in release_keys, "old OAI gNB release survived")
    for expected in (
        ("oai", "oai-5g-basic", "deployed"),
        ("oai", "oai-du", "uninstalled"),
        ("oai", "srsran-gnb", "deployed"),
        ("oai", "oai-flexric", "deployed"),
        ("oai", "oai-nr-ue", "deployed"),
        ("other", "oai-gnb", "deployed"),
    ):
        require(expected in release_keys, f"transition removed unrelated/history release {expected}")
    require("uninstall oai-gnb --namespace oai" in log, "OAI gNB was not uninstalled")
    require("uninstall oai-du" not in log, "uninstalled Helm history was treated as live ownership")
    require("--cascade foreground" in log and "--wait" in log and "--no-hooks" in log,
            "bounded Helm deletion semantics were lost")
    require(evidence["selected_ran"] == "srsran" and evidence["incompatible_ran"] == "oai",
            "wrong OAI->srsRAN evidence identity")


def check_srsran_to_oai() -> None:
    state = base_state()
    state["releases"] = [
        {"name": "oai-5g-basic", "namespace": "oai", "status": "deployed"},
        {"name": "oai-gnb", "namespace": "oai", "status": "deployed"},
        {"name": "srsran-gnb", "namespace": "oai", "status": "deployed"},
        {"name": "srsran-ue", "namespace": "oai", "status": "deployed"},
        {"name": "srsran-gnb", "namespace": "other", "status": "deployed"},
    ]
    state["deployments"]["items"] = [
        deployment("oai", "oai-gnb"),
        deployment("oai", "srsran-gnb"),
        deployment("other", "srsran-gnb"),
    ]
    state["pods"]["items"] = [
        pod("oai", "oai-gnb-selected", {"app.kubernetes.io/instance": "oai-gnb"}),
        pod("oai", "srsran-gnb-old", {"app": "srsran", "component": "gnb"}),
        pod("oai", "srsran-ue", {"app": "srsran", "component": "ue"}),
        pod("other", "srsran-gnb-other", {"app": "srsran", "component": "gnb"}),
    ]
    state["nads"]["items"] = [
        nad("oai", "oai-gnb-ru"),
        nad("oai", "ru-network"),
        nad("other", "ru-network"),
    ]

    evidence, final, log = run_fixture("oai", state)
    release_keys = {(item["namespace"], item["name"]) for item in final["releases"]}
    require(("oai", "srsran-gnb") not in release_keys, "old srsRAN gNB release survived")
    for expected in (
        ("oai", "oai-5g-basic"),
        ("oai", "oai-gnb"),
        ("oai", "srsran-ue"),
        ("other", "srsran-gnb"),
    ):
        require(expected in release_keys, f"transition removed unrelated release {expected}")
    require("uninstall srsran-gnb --namespace oai" in log, "srsRAN gNB was not uninstalled")
    require(evidence["selected_ran"] == "oai" and evidence["incompatible_ran"] == "srsran",
            "wrong srsRAN->OAI evidence identity")


def check_orphan_cleanup() -> None:
    state = base_state()
    state["deployments"]["items"] = [deployment("oai", "oai-gnb")]
    state["pods"]["items"] = [
        pod("oai", "oai-gnb-orphan", {"app.kubernetes.io/instance": "oai-gnb"})
    ]
    state["nads"]["items"] = [nad("oai", "oai-gnb-ru")]

    evidence, final, log = run_fixture("srsran", state)
    require(log == "", "orphan cleanup unexpectedly required Helm ownership")
    require(final["deployments"]["items"] == [], "orphan deployment survived")
    require(final["pods"]["items"] == [], "orphan pod survived")
    require(final["nads"]["items"] == [], "orphan RU NAD survived")
    require(evidence["remaining_deployments"] == [], "orphan deployment survived evidence")
    require(evidence["remaining_pods"] == [], "orphan pod survived evidence")
    require(evidence["remaining_ru_nads"] == [], "orphan NAD survived evidence")


def main() -> None:
    static_contract()
    check_oai_to_srsran()
    check_srsran_to_oai()
    check_orphan_cleanup()
    print("shared physical cross-RAN transition contract OK")


if __name__ == "__main__":
    main()
