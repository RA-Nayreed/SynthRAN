#!/usr/bin/env python3
"""Apply the selected transport plan without changing frozen sensor mappings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from synthran.experiment_scenario import scientific_settings

DEFAULT_PLAN = Path(__file__).with_name("pilot-plan-v1.json")


def prepare(pilot_root: Path, output: Path, plan_path: Path = DEFAULT_PLAN) -> Path:
    source = pilot_root / "native/model/resolved-scenario.yml"
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing transport scenario: {output}")
    scenario = yaml.safe_load(source.read_text())
    plan = json.loads(plan_path.read_text())["transport_baseline"]
    gateways = list(
        dict.fromkeys(device["gateway"] for device in scenario["devices"].values())
    )
    competing = plan["competing_traffic_ue"]
    if competing in gateways:
        raise SystemExit(f"{competing} is already a workload gateway")
    if not set(gateways) <= set(plan["workload_gateways"]):
        raise SystemExit(
            "Source gateway mapping does not match the selected transport plan"
        )
    deployment = {
        "core": plan["core"],
        "ran": plan["ran"],
        "platform": plan["software_platform"],
        "nodes": {role: plan[role + "_node"] for role in ("core", "ran", "broker")},
        "profile": plan["profile"],
        "ues": plan["workload_gateways"] + [competing],
        "reservation": plan["reservation"],
    }
    for key in (
        "host_vars",
        "ansible_vars",
        "ue_profiles",
        "profile_file",
        "topology_file",
    ):
        if key in plan:
            deployment[key] = plan[key]
    for key in ("profile_file", "topology_file"):
        if key in deployment:
            deployment[key] = str(
                (plan_path.resolve().parent / deployment[key]).resolve()
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    settings = output.with_name(output.stem + "-experiment.yml")
    if settings.exists():
        raise SystemExit(
            f"Refusing to overwrite existing experiment configuration: {settings}"
        )
    settings.write_text(
        yaml.safe_dump(scientific_settings(scenario), sort_keys=False)
    )
    value = {
        "deployment": deployment,
        "experiment": {
            "entrypoint": str(ROOT / "synthran/experiment_runner.py"),
            "config": str(settings.resolve()),
        },
    }
    output.write_text(yaml.safe_dump(value, sort_keys=False))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--pilot-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.pilot_root, args.output, args.plan))
