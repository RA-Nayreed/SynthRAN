#!/usr/bin/env python3
"""Build a modern accepted-testbed scenario for the complete Experiment-2 campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_PLAN = HERE / "experiment-plan.json"


def build(prepared_root: Path, output_root: Path, plan: dict, profile_name: str) -> dict:
    index = json.loads((prepared_root / "prepared-index.json").read_text(encoding="utf-8"))
    if index.get("status") != "complete" or index.get("transport_profile") != profile_name:
        raise SystemExit("prepared Experiment-2 cohort does not match the requested transport profile")
    seeds = sorted(int(row["seed"]) for row in index["sources"])
    if not seeds:
        raise SystemExit("prepared Experiment-2 cohort has no source seeds")
    native = prepared_root / f"seed{seeds[0]:05d}" / "native/model/resolved-scenario.yml"
    science = yaml.safe_load(native.read_text(encoding="utf-8")) or {}
    if not isinstance(science, dict):
        raise SystemExit("prepared scientific scenario is invalid")

    profile = plan["transport_profiles"][profile_name]
    workload = str(profile["workload_gateway"])
    competitor = str(profile["competing_traffic_ue"])
    for device in science.get("devices", {}).values():
        device["gateway"] = workload
    science["gateways"] = [workload]
    science.setdefault("mqtt", {})["drain_seconds"] = max(
        float(science.get("mqtt", {}).get("drain_seconds", 60)),
        float(plan["measurement"]["deadline_seconds"]),
    )
    science["measurement"] = {
        "warmup_seconds": float(plan["timing_interventions"]["warmup_seconds"]),
        "deadline_seconds": float(plan["measurement"]["deadline_seconds"]),
        "age_limit_seconds": float(plan["measurement"]["age_limit_seconds"]),
    }

    output_root.mkdir(parents=True, exist_ok=True)
    science_path = output_root / "transport-experiment.yml"
    scenario_path = output_root / "transport.yml"
    if science_path.exists() or scenario_path.exists():
        raise SystemExit(f"refusing to overwrite existing transport configuration: {output_root}")
    science_path.write_text(yaml.safe_dump(science, sort_keys=False), encoding="utf-8")

    deployment = {
        "core": profile["core"],
        "ran": profile["ran"],
        "platform": profile["platform"],
        "nodes": profile["nodes"],
        "network_profile": profile["network_profile"],
        "ues": [workload, competitor],
        "ue_slices": profile["ue_slices"],
    }
    if profile.get("reservation"):
        deployment["reservation"] = profile["reservation"]
    if profile["platform"] == "r2lab":
        deployment["ru"] = profile["ru"]
    if profile.get("host_vars"):
        deployment["host_vars"] = profile["host_vars"]
    if profile.get("ansible_vars"):
        deployment["ansible_vars"] = profile["ansible_vars"]

    scenario = {
        "deployment": deployment,
        "experiment": {
            "entrypoint": str((ROOT / "synthran/experiment_runtime/runner.py").resolve()),
            "config": str(science_path.resolve()),
        },
    }
    scenario_path.write_text(yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8")
    record = {
        "schema_version": 1,
        "status": "prepared",
        "transport_profile": profile_name,
        "workload_gateway": workload,
        "competing_traffic_ue": competitor,
        "scenario": str(scenario_path.resolve()),
        "scientific_config": str(science_path.resolve()),
    }
    (output_root / "transport-config.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--transport", choices=("r2lab", "rfsim"), default="r2lab")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    record = build(
        args.prepared_root.expanduser().resolve(),
        args.output.expanduser().resolve(),
        plan,
        args.transport,
    )
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
