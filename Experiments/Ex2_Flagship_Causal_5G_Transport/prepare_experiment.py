#!/usr/bin/env python3
"""Prepare the complete Experiment-2 matched timing cohort from frozen Experiment-1 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import yaml

from synthran.workload.bundle import (
    canonical,
    read_events,
    transform_bundle,
    validate_bundle,
    write_manifest,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_PLAN = HERE / "experiment-plan.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"required evidence is missing: {path}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"expected a JSON object: {path}")
    return value


def _design_digest(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "design_sha256"}
    return hashlib.sha256(canonical(payload)).hexdigest()


def _verify_campaign(campaign_root: Path, plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    selection = plan["source_selection"]
    campaign = _read_json(campaign_root / "campaign.json")
    design = _read_json(campaign_root / "frozen-design.json")
    index = _read_json(campaign_root / "runs/index.json")

    if campaign.get("experiment") != "ex1":
        raise SystemExit("upstream campaign is not Experiment 1")
    if campaign.get("campaign_id") != selection["experiment_1_campaign_id"]:
        raise SystemExit("upstream campaign ID differs from the Experiment-2 plan")
    if campaign.get("source_revision") != selection["experiment_1_source_revision"]:
        raise SystemExit("upstream source revision differs from the Experiment-2 plan")
    missing = sorted(
        set(selection.get("require_completed_phases", []))
        - set(campaign.get("completed_phases", []))
    )
    if missing:
        raise SystemExit("upstream campaign is incomplete: " + ", ".join(missing))

    if design.get("experiment") != "ex1" or _design_digest(design) != design.get("design_sha256"):
        raise SystemExit("upstream frozen design failed its integrity check")
    if design.get("campaign_id") != campaign["campaign_id"]:
        raise SystemExit("upstream frozen design belongs to a different campaign")
    if design.get("source_revision") != campaign["source_revision"]:
        raise SystemExit("upstream frozen design source revision differs from campaign metadata")
    if int(design.get("design_version", -1)) != int(selection["experiment_1_design_version"]):
        raise SystemExit("upstream design version differs from the Experiment-2 plan")

    if index.get("status") != "complete":
        raise SystemExit("upstream confirmation index is incomplete")
    if index.get("frozen_design_sha256") != design["design_sha256"]:
        raise SystemExit("upstream confirmation index does not match the frozen design")
    if int(index.get("runs_valid", -1)) != int(index.get("runs_expected", -2)):
        raise SystemExit("upstream confirmation cohort is incomplete")

    confirmation = design["confirmation"]
    condition = selection["condition"]
    if condition not in confirmation["conditions"]:
        raise SystemExit(f"upstream design has no condition {condition!r}")
    frozen_seeds = [int(value) for value in confirmation["seeds"]]
    if selection.get("seed_policy") != "all_frozen_confirmation_seeds":
        raise SystemExit("Experiment 2 requires all frozen confirmation seeds")
    if len(frozen_seeds) != int(selection["expected_seed_count"]):
        raise SystemExit("frozen source-seed count differs from the Experiment-2 plan")

    rows = [
        row
        for row in index.get("runs", [])
        if row.get("condition") == condition and int(row.get("seed", -1)) in set(frozen_seeds)
    ]
    by_seed = {int(row["seed"]): row for row in rows}
    if sorted(by_seed) != sorted(frozen_seeds) or len(rows) != len(frozen_seeds):
        raise SystemExit("upstream index does not contain exactly one selected source per frozen seed")
    return campaign, design, [by_seed[seed] for seed in sorted(frozen_seeds)]


def _source_scenario(bundle: Path) -> dict[str, Any]:
    value = yaml.safe_load((bundle / "resolved-scenario.yml").read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict) or not isinstance(value.get("devices"), dict):
        raise SystemExit(f"invalid upstream resolved scenario: {bundle}")
    return value


def _write_transport_source(
    source: Path,
    destination: Path,
    *,
    gateway: str,
    profile: str,
    campaign_id: str,
    condition: str,
    seed: int,
) -> dict[str, Any]:
    manifest = validate_bundle(source)
    if manifest.get("transformation", {}).get("variant", "native") != "native":
        raise SystemExit("Experiment-2 inputs must originate from native Experiment-1 bundles")
    if destination.exists():
        raise SystemExit(f"refusing to overwrite prepared source: {destination}")
    destination.mkdir(parents=True)

    scenario = _source_scenario(source)
    devices = scenario["devices"]
    original_mapping = {name: cfg.get("gateway", name) for name, cfg in devices.items()}
    for cfg in devices.values():
        cfg["gateway"] = gateway
    scenario["gateways"] = [gateway]
    (destination / "resolved-scenario.yml").write_text(
        yaml.safe_dump(scenario, sort_keys=False),
        encoding="utf-8",
    )

    source_events = read_events(source / "events.jsonl")
    with (destination / "events.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for event in source_events:
            derived = dict(event)
            derived["gateway"] = gateway
            stream.write(canonical(derived).decode("utf-8") + "\n")

    metadata = {
        key: value
        for key, value in manifest.items()
        if key not in {"files", "bundle_sha256", "sensor_gateways", "transformation"}
    }
    metadata["sensor_gateways"] = {name: gateway for name in devices}
    metadata["transformation"] = {
        "variant": "native",
        "generation_age_valid": True,
        "source_bundle_sha256": manifest["bundle_sha256"],
    }
    metadata["transport_source"] = {
        "upstream_experiment": "ex1",
        "upstream_campaign_id": campaign_id,
        "upstream_condition": condition,
        "upstream_seed": seed,
        "upstream_bundle_sha256": manifest["bundle_sha256"],
        "transport_profile": profile,
        "transport_gateway": gateway,
        "original_sensor_gateways": original_mapping,
        "mapping_change_scope": (
            "transport-only gateway consolidation before all timing interventions; "
            "sensor identity, event order, payload bytes, topics and event count are unchanged"
        ),
    }
    return write_manifest(destination, metadata)


def _permutation_seed(campaign_id: str, condition: str, seed: int, arm: str) -> int:
    digest = hashlib.sha256(
        f"{campaign_id}|{condition}|{seed}|{arm}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big")


def _event_signature(path: Path) -> list[tuple[str, str, str, str]]:
    return [
        (row["event_id"], row["device"], row["topic"], row["payload"])
        for row in read_events(path)
    ]


def _measurement_offsets(path: Path, warmup: float) -> list[float]:
    return [
        float(row["time_offset_s"])
        for row in read_events(path)
        if float(row["time_offset_s"]) >= warmup
    ]


def _verify_arm_invariants(base: Path, arms: dict[str, Path], warmup: float) -> dict[str, Any]:
    source_signature = _event_signature(base / "events.jsonl")
    native_offsets = _measurement_offsets(base / "events.jsonl", warmup)
    source_events = read_events(base / "events.jsonl")
    source_gateways = [row.get("gateway") for row in source_events]
    report: dict[str, Any] = {}

    for arm, directory in arms.items():
        manifest = validate_bundle(directory)
        events = read_events(directory / "events.jsonl")
        if _event_signature(directory / "events.jsonl") != source_signature:
            raise SystemExit(f"{arm} changed event identity, order, topic or payload")
        if [row.get("gateway") for row in events] != source_gateways:
            raise SystemExit(f"{arm} changed the transport gateway assignment")
        offsets = _measurement_offsets(directory / "events.jsonl", warmup)
        if len(offsets) != len(native_offsets):
            raise SystemExit(f"{arm} changed measurement event count")
        if len(offsets) >= 2 and (
            not math.isclose(offsets[0], native_offsets[0], abs_tol=1e-12)
            or not math.isclose(offsets[-1], native_offsets[-1], abs_tol=1e-12)
        ):
            raise SystemExit(f"{arm} changed measurement endpoints")
        if arm.startswith("gap_permutation") and len(offsets) >= 2:
            native_gaps = sorted(b - a for a, b in zip(native_offsets, native_offsets[1:]))
            arm_gaps = sorted(b - a for a, b in zip(offsets, offsets[1:]))
            if len(native_gaps) != len(arm_gaps) or any(
                not math.isclose(a, b, abs_tol=1e-10)
                for a, b in zip(native_gaps, arm_gaps)
            ):
                raise SystemExit(f"{arm} did not preserve the measurement gap multiset")
        report[arm] = {
            "bundle_sha256": manifest["bundle_sha256"],
            "event_count": manifest["event_count"],
            "generation_age_valid": manifest["transformation"]["generation_age_valid"],
        }
    return report


def prepare(
    campaign_root: Path,
    output_root: Path,
    plan: dict[str, Any],
    profile_name: str,
) -> dict[str, Any]:
    if output_root.exists():
        raise SystemExit(f"refusing to overwrite prepared Experiment-2 directory: {output_root}")
    profile = plan["transport_profiles"].get(profile_name)
    if not isinstance(profile, dict):
        raise SystemExit(f"unknown transport profile: {profile_name}")

    campaign, design, source_rows = _verify_campaign(campaign_root.resolve(), plan)
    output_root.mkdir(parents=True)
    condition = plan["source_selection"]["condition"]
    warmup = float(plan["timing_interventions"]["warmup_seconds"])
    arms = list(plan["timing_interventions"]["arms"])
    if set(arms) != {"native", "gap_permutation_r1", "gap_permutation_r2", "periodic"}:
        raise SystemExit("Experiment-2 timing-arm contract is incomplete")

    prepared_rows = []
    for position, row in enumerate(source_rows, start=1):
        seed = int(row["seed"])
        source = (campaign_root / row["path"] / "model").resolve()
        source_manifest = validate_bundle(source)
        if source_manifest["bundle_sha256"] != row["bundle_sha256"]:
            raise SystemExit(f"upstream bundle SHA-256 differs from index for seed {seed}")

        seed_root = output_root / f"seed{seed:05d}"
        base = seed_root / "transport-source"
        base_manifest = _write_transport_source(
            source,
            base,
            gateway=str(profile["workload_gateway"]),
            profile=profile_name,
            campaign_id=campaign["campaign_id"],
            condition=condition,
            seed=seed,
        )
        destinations = {
            "native": seed_root / "native" / "model",
            "gap_permutation_r1": seed_root / "gap_permutation_r1" / "model",
            "gap_permutation_r2": seed_root / "gap_permutation_r2" / "model",
            "periodic": seed_root / "periodic" / "model",
        }
        for arm, destination in destinations.items():
            variant = (
                "gap_permutation"
                if arm.startswith("gap_permutation")
                else arm
            )
            transform_bundle(
                base,
                destination,
                variant,
                seed=_permutation_seed(campaign["campaign_id"], condition, seed, arm),
                warmup_seconds=warmup,
            )
        arm_report = _verify_arm_invariants(base, destinations, warmup)
        prepared_rows.append(
            {
                "seed": seed,
                "condition": condition,
                "upstream_bundle_sha256": row["bundle_sha256"],
                "transport_source_bundle_sha256": base_manifest["bundle_sha256"],
                "arms": arm_report,
            }
        )
        print(f"Prepared {position}/{len(source_rows)}: {condition} seed {seed}", flush=True)

    record = {
        "schema_version": 1,
        "status": "complete",
        "experiment": plan["experiment"],
        "upstream_campaign_id": campaign["campaign_id"],
        "upstream_source_revision": campaign["source_revision"],
        "upstream_frozen_design_sha256": design["design_sha256"],
        "condition": condition,
        "transport_profile": profile_name,
        "transport_gateway": profile["workload_gateway"],
        "source_seed_count": len(prepared_rows),
        "timing_arms": arms,
        "expected_confirmation_replays": (
            len(prepared_rows)
            * len(arms)
            * len(plan["confirmation"]["load_levels"])
        ),
        "sources": prepared_rows,
    }
    (output_root / "prepared-index.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "plan-snapshot.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Experiment-2 inputs complete: {len(prepared_rows)} sources × "
        f"{len(arms)} timing arms",
        flush=True,
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment1-campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--transport", choices=("r2lab", "rfsim"), default="r2lab")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    args = parser.parse_args()
    plan = _read_json(args.plan.resolve())
    prepare(
        args.experiment1_campaign.expanduser().resolve(),
        args.output.expanduser().resolve(),
        plan,
        args.transport,
    )


if __name__ == "__main__":
    main()
