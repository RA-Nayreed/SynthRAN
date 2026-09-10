#!/usr/bin/env python3
"""Select the frozen Experiment-1 pilot source and build Experiment-2 timing bundles."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import yaml

from synthran.workload.bundle import transform_bundle, validate_bundle


DEFAULT_RESULTS = Path("results/exp1-energy-correlation")
DEFAULT_OUTPUT = Path("results/exp2-matched-trace/pilot-seed1001")
SOURCE_SEED = 1001
SOURCE_MEAN_POWER_W = 0.001
SOURCE_SENSOR_COUNT = 32
SOURCE_DURATION_SECONDS = 60.0
WARMUP_SECONDS = 10.0
GAP_PERMUTATION_SEED = 101


def _scenario(bundle: Path) -> dict:
    source = bundle / "resolved-scenario.yml"
    if not source.is_file():
        raise ValueError(f"bundle is missing resolved-scenario.yml: {bundle}")
    value = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"scenario is not a mapping: {source}")
    return value


def _matches_frozen_source(bundle: Path) -> bool:
    try:
        manifest = validate_bundle(bundle)
        scenario = _scenario(bundle)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError):
        return False

    model = scenario.get("model", {})
    energy = model.get("energy", {})
    devices = scenario.get("devices", {})
    transformation = manifest.get("transformation", {})
    return (
        model.get("seed") == SOURCE_SEED
        and energy.get("source") == "lognormal"
        and energy.get("correlation") == "common"
        and math.isclose(
            float(energy.get("mean_power_w", float("nan"))),
            SOURCE_MEAN_POWER_W,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and isinstance(devices, dict)
        and len(devices) == SOURCE_SENSOR_COUNT
        and math.isclose(
            float(manifest.get("duration_seconds", float("nan"))),
            SOURCE_DURATION_SECONDS,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        and transformation.get("variant", "native") == "native"
    )


def find_source(root: Path) -> Path:
    candidates = []
    for manifest in sorted(root.glob("*/source-manifest.json")):
        bundle = manifest.parent
        if _matches_frozen_source(bundle):
            candidates.append(bundle.resolve())
    if len(candidates) != 1:
        rendered = "\n".join(f"  {candidate}" for candidate in candidates) or "  <none>"
        raise SystemExit(
            "Expected exactly one frozen knee-common Experiment-1 source bundle "
            f"(seed={SOURCE_SEED}, mean_power_w={SOURCE_MEAN_POWER_W}, "
            f"sensors={SOURCE_SENSOR_COUNT}, duration={SOURCE_DURATION_SECONDS}s); "
            f"found {len(candidates)}:\n{rendered}"
        )
    return candidates[0]


def prepare(source_root: Path, output_root: Path) -> dict:
    source = find_source(source_root)
    source_manifest = validate_bundle(source)
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemExit(f"Refusing to overwrite existing pilot directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    destinations = {
        "native": output_root / "native" / "model",
        "gap_permutation": output_root / "gap_permutation" / "model",
        "periodic": output_root / "periodic" / "model",
    }
    transform_bundle(
        source,
        destinations["native"],
        "native",
        seed=GAP_PERMUTATION_SEED,
        warmup_seconds=WARMUP_SECONDS,
    )
    transform_bundle(
        source,
        destinations["gap_permutation"],
        "gap_permutation",
        seed=GAP_PERMUTATION_SEED,
        warmup_seconds=WARMUP_SECONDS,
    )
    transform_bundle(
        source,
        destinations["periodic"],
        "periodic",
        seed=GAP_PERMUTATION_SEED,
        warmup_seconds=WARMUP_SECONDS,
    )

    variants = {
        name: validate_bundle(path) for name, path in destinations.items()
    }
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
            "model_seed": SOURCE_SEED,
            "mean_power_w": SOURCE_MEAN_POWER_W,
            "energy_correlation": "common",
            "sensor_count": SOURCE_SENSOR_COUNT,
            "duration_seconds": SOURCE_DURATION_SECONDS,
        },
        "warmup_seconds": WARMUP_SECONDS,
        "gap_permutation_seed": GAP_PERMUTATION_SEED,
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
    parser.add_argument("--experiment1-root", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    record = prepare(args.experiment1_root, args.output)
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
