#!/usr/bin/env python3
"""Build Experiment-2 timing bundles from the frozen current Experiment-1 v2 campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from synthran.workload.bundle import transform_bundle, validate_bundle

DEFAULT_PLAN = Path(__file__).with_name("pilot-plan.json")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Required Experiment-1 evidence is missing: {path}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object: {path}")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _validate_frozen_design(value: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    expected = value.get("design_sha256")
    payload = {key: item for key, item in value.items() if key != "design_sha256"}
    observed = hashlib.sha256(_canonical(payload)).hexdigest()
    if not isinstance(expected, str) or observed != expected:
        raise SystemExit("Experiment-1 frozen-design.json failed its SHA-256 integrity check")
    if value.get("experiment") != "ex1":
        raise SystemExit("Selected upstream campaign is not Experiment 1")
    if int(value.get("design_version", -1)) != int(
        selection["experiment_1_design_version"]
    ):
        raise SystemExit("Experiment-1 design version differs from the Experiment-2 plan")
    if value.get("campaign_id") != selection["experiment_1_campaign_id"]:
        raise SystemExit("Experiment-1 frozen design belongs to a different campaign")
    if value.get("source_revision") != selection["experiment_1_source_revision"]:
        raise SystemExit("Experiment-1 source revision differs from the Experiment-2 plan")
    return value


def _scenario(bundle: Path) -> dict[str, Any]:
    source = bundle / "resolved-scenario.yml"
    if not source.is_file():
        raise SystemExit(f"Bundle is missing resolved-scenario.yml: {bundle}")
    value = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise SystemExit(f"Scenario is not a mapping: {source}")
    return value


def _resolve_source(
    campaign_root: Path,
    plan: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    campaign_root = campaign_root.resolve()
    selection = plan["source_selection"]

    campaign = _read_json(campaign_root / "campaign.json")
    if campaign.get("experiment") != "ex1":
        raise SystemExit("Selected upstream campaign is not Experiment 1")
    if campaign.get("campaign_id") != selection["experiment_1_campaign_id"]:
        raise SystemExit(
            "Experiment-2 is pinned to a different Experiment-1 campaign: "
            f"{selection['experiment_1_campaign_id']}"
        )
    if campaign.get("source_revision") != selection["experiment_1_source_revision"]:
        raise SystemExit("Experiment-1 campaign source revision differs from the plan")

    completed = set(campaign.get("completed_phases", []))
    required = set(selection.get("require_completed_phases", []))
    missing = sorted(required - completed)
    if missing:
        raise SystemExit(
            "Experiment-1 v2 is not ready for downstream use; missing completed phase(s): "
            + ", ".join(missing)
        )

    design = _validate_frozen_design(
        _read_json(campaign_root / "frozen-design.json"),
        selection,
    )
    confirmation = design.get("confirmation", {})
    condition = selection["experiment_1_condition"]
    conditions = confirmation.get("conditions", {})
    if condition not in conditions:
        raise SystemExit(f"Frozen Experiment-1 design has no condition {condition!r}")

    seeds = [int(value) for value in confirmation.get("seeds", [])]
    if not seeds:
        raise SystemExit("Frozen Experiment-1 design has no confirmation seeds")
    if selection.get("seed_policy") != "first_frozen_confirmation_seed":
        raise SystemExit("Unsupported Experiment-2 source seed policy")
    seed = seeds[0]

    index = _read_json(campaign_root / "runs/index.json")
    if index.get("status") != "complete":
        raise SystemExit("Experiment-1 confirmation index is not complete")
    if index.get("frozen_design_sha256") != design["design_sha256"]:
        raise SystemExit("Experiment-1 confirmation index does not match the frozen design")
    if int(index.get("runs_valid", -1)) != int(index.get("runs_expected", -2)):
        raise SystemExit("Experiment-1 confirmation cohort is incomplete")

    matches = [
        row
        for row in index.get("runs", [])
        if row.get("condition") == condition and int(row.get("seed", -1)) == seed
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"Expected exactly one Experiment-1 source for {condition} seed {seed}"
        )
    row = matches[0]
    bundle = (campaign_root / row["path"] / "model").resolve()
    manifest = validate_bundle(bundle)
    if manifest.get("bundle_sha256") != row.get("bundle_sha256"):
        raise SystemExit("Experiment-1 source bundle SHA-256 differs from its confirmation index")

    scenario = _scenario(bundle)
    model = scenario.get("model", {})
    energy = model.get("energy", {})
    devices = scenario.get("devices", {})
    expected_energy = conditions[condition]
    expected_sensor_count = int(confirmation["sensor_count"])
    duration = float(design["model_contract"]["measurement"]["duration_seconds"])

    if int(model.get("seed", -1)) != seed:
        raise SystemExit("Experiment-1 source scenario seed differs from the frozen source")
    if not isinstance(devices, dict) or len(devices) != expected_sensor_count:
        raise SystemExit("Experiment-1 source population differs from the frozen design")
    if energy.get("mode") != expected_energy.get("mode"):
        raise SystemExit("Experiment-1 source energy mode differs from the frozen design")
    if energy.get("source") != expected_energy.get("source"):
        raise SystemExit("Experiment-1 source energy source differs from the frozen design")
    if energy.get("correlation") != expected_energy.get("correlation"):
        raise SystemExit("Experiment-1 source energy correlation differs from the frozen design")
    if not math.isclose(
        float(energy.get("mean_power_w", float("nan"))),
        float(expected_energy["mean_power_w"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise SystemExit("Experiment-1 source power differs from the frozen design")
    if not math.isclose(
        float(manifest.get("duration_seconds", float("nan"))),
        duration,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise SystemExit("Experiment-1 source duration differs from the frozen design")
    if manifest.get("transformation", {}).get("variant", "native") != "native":
        raise SystemExit("Experiment-2 source must be an untransformed native Experiment-1 bundle")

    source = {
        "campaign_id": campaign["campaign_id"],
        "source_revision": campaign["source_revision"],
        "design_version": design["design_version"],
        "frozen_design_sha256": design["design_sha256"],
        "condition": condition,
        "model_seed": seed,
        "sensor_count": expected_sensor_count,
        "energy": expected_energy,
        "duration_seconds": duration,
        "bundle_sha256": manifest["bundle_sha256"],
        "confirmation_index_path": str((campaign_root / "runs/index.json").resolve()),
        "path": str(bundle),
    }
    return bundle, source


def prepare(
    campaign_root: Path,
    output_root: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    source, source_record = _resolve_source(campaign_root, plan)
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemExit(f"Refusing to overwrite existing pilot directory: {output_root}")
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
            seed=int(plan["timing_interventions"]["gap_permutation_seed"]),
            warmup_seconds=float(plan["timing_interventions"]["warmup_seconds"]),
        )

    variants = {name: validate_bundle(path) for name, path in destinations.items()}
    native_events = (destinations["native"] / "events.jsonl").read_bytes()
    source_events = (source / "events.jsonl").read_bytes()
    if native_events != source_events:
        raise SystemExit("Native Experiment-2 bundle changed the Experiment-1 source trace")

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
            raise SystemExit(f"{name} changed Experiment-1 event identity/order")

    record = {
        "schema_version": 2,
        "experiment": "exp2-matched-trace-transport",
        "phase": "transport-operating-point-pilot",
        "source": source_record,
        "warmup_seconds": float(plan["timing_interventions"]["warmup_seconds"]),
        "gap_permutation_seed": int(
            plan["timing_interventions"]["gap_permutation_seed"]
        ),
        "variants": {
            name: {
                "path": str(path.resolve()),
                "bundle_sha256": manifest["bundle_sha256"],
                "event_count": manifest["event_count"],
                "generation_age_valid": manifest["transformation"][
                    "generation_age_valid"
                ],
            }
            for name, path, manifest in (
                (name, destinations[name], variants[name]) for name in destinations
            )
        },
    }
    (output_root / "pilot-source-selection.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--experiment1-campaign", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    plan = _read_json(args.plan)
    selection = plan["source_selection"]
    campaign = (
        args.experiment1_campaign.expanduser().resolve()
        if args.experiment1_campaign
        else (
            ROOT
            / "results/experiments/ex1"
            / selection["experiment_1_campaign_id"]
        ).resolve()
    )
    output = (
        args.output.expanduser().resolve()
        if args.output
        else (
            ROOT
            / "results/exp2-matched-trace"
            / selection["experiment_1_campaign_id"]
            / "pilot"
        ).resolve()
    )
    record = prepare(campaign, output, plan)
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
