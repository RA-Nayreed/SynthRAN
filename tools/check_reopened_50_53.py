#!/usr/bin/env python3
"""Regression contract for the reopened findings in issues #50 and #53."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def require(text: str, needle: str, context: str) -> None:
    if needle not in text:
        raise SystemExit(f"{context}: missing {needle!r}")


def task(tasks: list[dict], name: str) -> dict:
    for item in tasks:
        if item.get("name") == name:
            return item
    raise SystemExit(f"pre_k8s: missing task {name!r}")


def when_text(item: dict) -> str:
    value = item.get("when", "")
    return "\n".join(map(str, value)) if isinstance(value, list) else str(value)


provision_path = ROOT / "deployment/playbooks/provision_nodes.yml"
provision = provision_path.read_text(encoding="utf-8")
require(provision, "findmnt --nofsroot -n -o SOURCE /var/lib/containerd", "provision_nodes")

pre_path = ROOT / "deployment/roles/setup/pre_k8s/tasks/main.yml"
pre_text = pre_path.read_text(encoding="utf-8")
pre = yaml.safe_load(pre_text)
require(pre_text, "Check whether selected storage already backs containerd", "pre_k8s")
require(pre_text, "findmnt --nofsroot -n -o SOURCE /var/lib/containerd", "pre_k8s")
for name in (
    "Remove stale /var/lib/containerd fstab entries",
    "Clear stale containerd mounts",
    "Create the containerd directory on already-mounted storage",
    "Bind already-mounted storage to the containerd data directory",
    "Mount unmounted ext4 storage at the containerd data directory",
):
    if "containerd_existing_binding.stdout | trim != 'selected'" not in when_text(task(pre, name)):
        raise SystemExit(f"pre_k8s: {name!r} can mutate an already-correct selected-device binding")

scenario = (ROOT / "synthran/scenario.py").read_text(encoding="utf-8")
require(scenario, "topology not found", "scenario source validation")
require(scenario, "invalid selected topology", "scenario source validation")

print("reopened #50/#53 regression contract OK")
