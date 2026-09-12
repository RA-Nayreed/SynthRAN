#!/usr/bin/env python3
"""Select the frozen Experiment-1 pilot source and build Experiment-2 timing bundles."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from synthran.workload.bundle import transform_bundle, validate_bundle

DEFAULT_RESULTS = Path("results/exp1-energy-correlation")
DEFAULT_OUTPUT = Path("results/exp2-matched-trace/pilot-seed1001")
DEFAULT_PLAN = Path(__file__).with_name("pilot-plan-v1.json")


def _scenario(bundle: Path) -> dict:
    source = bundle / "resolved-scenario.yml"
    if not source.is_file():
        raise ValueError(f"bundle is missing resolved-scenario.yml: {bundle}")
    value = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"scenario is not a mapping: {source}")
    return value


def _matches_frozen_source(bundle: Path, plan: dict) -> bool:
    try:
        manifest = validate_bundle(bundle)
        scenario = _scenario(bundle)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        yaml.YAMLError,
    ):
        return False

    model = scenario.get("model", {})
    energy = model.get("energy", {})
    devices = scenario.get("devices", {})
    transformation = manifest.get("transformation", {})
    return (
        model.get("seed") == plan["source_selection"]["model_seed"]
        and energy.get("source") == plan["source_selection"]["energy_source"]
        and energy.get("correlation") == plan["source_selection"]["energy_correlation"]
        and math.isclose(
            float(energy.get("mean_power_w", float("nan"))),
            plan["source_selection"]["mean_power_w"],
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and isinstance(devices, dict)
        and len(devices) == plan["source_selection"]["sensor_count"]
        and math.isclose(
            float(manifest.get("duration_seconds", float("nan"))),
            plan["source_selection"]["duration_seconds"],
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        and transformation.get("variant", "native") == "native"
    )


def find_source(root: Path, plan: dict) -> Path:
    selection = plan["source_selection"]
    bundle = (
        root / f"{selection['experiment_1_condition']}-seed{selection['model_seed']}"
    )
    if not _matches_frozen_source(bundle, plan):
        raise SystemExit(
            f"Selected Experiment-1 source is missing or differs from the plan: {bundle}"
        )
    return bundle.resolve()


def prepare(source_root: Path, output_root: Path, plan: dict) -> dict:
    source = find_source(source_root, plan)
    source_manifest = validate_bundle(source)
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemExit(
            f"Refusing to overwrite existing pilot directory: {output_root}"
        )
    output_root.mkdir(parents=True, exist_ok=True)

    destinations = {
        variant: output_root / variant / "model"
        for variant in plan["timing_interventions"]["variants"]
    }
    for variant, destination in destinations.items():
        transform_bundle(
            source,
            destination,
            variant,
            seed=plan["timing_interventions"]["gap_permutation_seed"],
            warmup_seconds=plan["timing_interventions"]["warmup_seconds"],
        )

    variants = {name: validate_bundle(path) for name, path in destinations.items()}
    native_events = (destinations["native"] / "events.jsonl").read_bytes()
    source_events = (source / "events.jsonl").read_bytes()
    if native_events != source_events:
        raise SystemExit("Native Experiment-2 bundle changed the source event trace")

    source_ids = [
        json.loads(line)["event_id"]
        for line in (source / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for name, path in destinations.items():
        ids = [
            json.loads(line)["event_id"]
            for line in (path / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if ids != source_ids:
            raise SystemExit(f"{name} changed event identity/order")

    record = {
        "experiment": "exp2-matched-trace-transport",
        "phase": "transport-operating-point-pilot",
        "source": {
            "path": str(source),
            "bundle_sha256": source_manifest["bundle_sha256"],
            "model_seed": plan["source_selection"]["model_seed"],
            "mean_power_w": plan["source_selection"]["mean_power_w"],
            "energy_correlation": plan["source_selection"]["energy_correlation"],
            "sensor_count": plan["source_selection"]["sensor_count"],
            "duration_seconds": plan["source_selection"]["duration_seconds"],
        },
        "warmup_seconds": plan["timing_interventions"]["warmup_seconds"],
        "gap_permutation_seed": plan["timing_interventions"]["gap_permutation_seed"],
        "variants": {
            name: {
                "path": str(path.resolve()),
                "bundle_sha256": manifest["bundle_sha256"],
                "event_count": manifest["event_count"],
                "generation_age_valid": manifest["transformation"][
                    "generation_age_valid"
                ],
            }
            for name, (path, manifest) in (
                (name, (destinations[name], variants[name])) for name in destinations
            )
        },
    }
    (output_root / "pilot-source-selection.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--experiment1-root", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    record = prepare(
        args.experiment1_root, args.output, json.loads(args.plan.read_text())
    )
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
