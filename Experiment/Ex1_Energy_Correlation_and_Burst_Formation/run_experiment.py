#!/usr/bin/env python3
"""Reproduce Experiment 1 from its campaign plan and scientific template."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import yaml
from Experiment.workload.bundle import validate_bundle
from Experiment.workload.trace import generate


def scenario(plan: dict, template: dict, count: int, seed: int, spec: dict) -> dict:
    value = copy.deepcopy(template)
    model = value["model"]
    model.update(seed=seed, duration_seconds=plan["measurement"]["duration_seconds"])
    model["energy"] = {**model["energy"], **plan["energy_source"], **spec}
    # The template defines topology; the plan overrides the frozen study knobs.
    for section in ("protocol", "receiver"):
        model[section].update(plan["model"][section])
    value["devices"] = {
        f"sensor{index:02d}": {
            **plan["sensor"],
            "sensing_interval_ms": plan["measurement"]["sensing_interval_ms"],
            "gateway": value["gateways"][(index - 1) % len(value["gateways"])],
        }
        for index in range(1, count + 1)
    }
    return value


def run_one(root: Path, name: str, value: dict, resume: bool) -> None:
    output = root / name
    if output.exists() and any(output.iterdir()):
        if resume:
            validate_bundle(output)
            print(f"Skipped existing valid bundle: {name}")
            return
        raise SystemExit(f"Refusing to overwrite existing run: {output}")
    source = root / "_scenarios" / f"{name}.yml"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(yaml.safe_dump(value, sort_keys=False))
    generate(source, output)
    print(f"Completed {name}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", type=Path, default=Path(__file__).with_name("experiment-plan.json")
    )
    parser.add_argument("--results-root", type=Path)
    parser.add_argument(
        "--phase",
        choices=("power-calibration", "population-calibration", "confirmation", "all"),
        default="confirmation",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--condition", action="append")
    parser.add_argument("--seed", action="append", type=int)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    template = yaml.safe_load(
        (args.plan.parent / plan["scenario_template"]).read_text()
    )
    root = (args.results_root or ROOT / plan["raw_results_root"]).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.phase in ("power-calibration", "all"):
        section = plan["power_calibration"]
        for power in section["mean_power_w"]:
            for seed in section["seeds"]:
                spec = {
                    "mode": "environmental",
                    "correlation": section["correlation"],
                    "mean_power_w": power,
                }
                run_one(
                    root,
                    f"calibration-power-{round(power * 1e6)}uw-seed{seed}",
                    scenario(plan, template, section["sensor_count"], seed, spec),
                    args.resume,
                )
    if args.phase in ("population-calibration", "all"):
        section = plan["population_calibration"]
        for count in section["sensor_counts"]:
            for seed in section["seeds"]:
                spec = {
                    "mode": "environmental",
                    "correlation": section["correlation"],
                    "mean_power_w": section["mean_power_w"],
                }
                run_one(
                    root,
                    f"calibration-population-n{count}-seed{seed}",
                    scenario(plan, template, count, seed, spec),
                    args.resume,
                )
    if args.phase in ("confirmation", "all"):
        section = plan["confirmation"]
        conditions = args.condition or list(section["conditions"])
        seeds = args.seed or list(
            range(section["seeds"]["first"], section["seeds"]["last"] + 1)
        )
        if any(name not in section["conditions"] for name in conditions):
            parser.error("condition is absent from the selected plan")
        if any(
            not section["seeds"]["first"] <= seed <= section["seeds"]["last"]
            for seed in seeds
        ):
            parser.error("seed is outside the selected plan confirmation range")
        for condition in conditions:
            for seed in seeds:
                value = scenario(
                    plan,
                    template,
                    section["sensor_count"],
                    seed,
                    section["conditions"][condition],
                )
                run_one(root, f"{condition}-seed{seed}", value, args.resume)


if __name__ == "__main__":
    main()
