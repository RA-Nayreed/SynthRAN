"""Prepare and discover the transferable Experiment-2 source cohort.

The public launcher is ``experiment.sh``.  This module is an internal study
implementation: it selects the newest complete Experiment-1 campaign when raw
source evidence is local, creates the prespecified matched timing controls, and
stores them under a stable repository-local transfer path.  A transferred
prepared cohort is fully self-contained and can be validated on Duckburg
without the complete Experiment-1 campaign being present there.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from synthran.workload.bundle import canonical, read_events, transform_bundle, validate_bundle

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EX1_ROOT = ROOT / "results/experiments/ex1"
PREPARED_ROOT = ROOT / "results/experiments/ex2-source"
CONDITION = "knee-common"
ARMS = ("native", "gap_permutation_r1", "gap_permutation_r2", "periodic")
WARMUP_SECONDS = 10.0
EXPECTED_SOURCE_SEEDS = 30


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _design_digest(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "design_sha256"}
    return hashlib.sha256(canonical(payload)).hexdigest()


def _complete_ex1_candidates() -> list[Path]:
    if not EX1_ROOT.is_dir():
        return []
    result = []
    for root in EX1_ROOT.iterdir():
        campaign_file = root / "campaign.json"
        if not root.is_dir() or not campaign_file.is_file():
            continue
        try:
            campaign = _read_json(campaign_file)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        completed = set(campaign.get("completed_phases", []))
        if campaign.get("experiment") == "ex1" and {"confirmation", "analysis"}.issubset(completed):
            result.append(root)
    return sorted(result, key=lambda path: path.name)


def latest_complete_ex1() -> Path:
    candidates = _complete_ex1_candidates()
    if not candidates:
        raise ValueError(
            "no complete Experiment-1 campaign is local; prepare Ex2 on the machine that holds Ex1, "
            "then rsync results/experiments/ex2-source/ to this checkout"
        )
    return candidates[-1]


def _verify_upstream(campaign_root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    campaign = _read_json(campaign_root / "campaign.json")
    design = _read_json(campaign_root / "frozen-design.json")
    index = _read_json(campaign_root / "runs/index.json")
    if campaign.get("experiment") != "ex1":
        raise ValueError("selected upstream campaign is not Experiment 1")
    if not {"confirmation", "analysis"}.issubset(set(campaign.get("completed_phases", []))):
        raise ValueError("selected Experiment-1 campaign is incomplete")
    if design.get("experiment") != "ex1" or _design_digest(design) != design.get("design_sha256"):
        raise ValueError("Experiment-1 frozen design failed its integrity check")
    if design.get("campaign_id") != campaign.get("campaign_id"):
        raise ValueError("Experiment-1 frozen design belongs to another campaign")
    if design.get("source_revision") != campaign.get("source_revision"):
        raise ValueError("Experiment-1 source revision differs between campaign and frozen design")
    if index.get("status") != "complete":
        raise ValueError("Experiment-1 confirmation index is incomplete")
    if index.get("frozen_design_sha256") != design.get("design_sha256"):
        raise ValueError("Experiment-1 confirmation index does not match its frozen design")
    if int(index.get("runs_valid", -1)) != int(index.get("runs_expected", -2)):
        raise ValueError("Experiment-1 confirmation cohort is not fully valid")

    confirmation = design.get("confirmation", {})
    conditions = confirmation.get("conditions", [])
    if CONDITION not in conditions:
        raise ValueError(f"Experiment-1 frozen design has no {CONDITION!r} condition")
    seeds = [int(value) for value in confirmation.get("seeds", [])]
    if len(seeds) != EXPECTED_SOURCE_SEEDS:
        raise ValueError(
            f"Experiment 2 expects {EXPECTED_SOURCE_SEEDS} frozen source seeds; found {len(seeds)}"
        )
    wanted = set(seeds)
    rows = [
        row
        for row in index.get("runs", [])
        if row.get("condition") == CONDITION and int(row.get("seed", -1)) in wanted
    ]
    by_seed = {int(row["seed"]): row for row in rows}
    if sorted(by_seed) != sorted(seeds) or len(rows) != len(seeds):
        raise ValueError("Experiment-1 index does not contain exactly one knee-common source per frozen seed")
    return campaign, design, [by_seed[seed] for seed in sorted(seeds)]


def _signature(path: Path) -> list[tuple[str, str, str, str, str | None]]:
    return [
        (
            row["event_id"],
            row["device"],
            row["topic"],
            row["payload"],
            row.get("gateway"),
        )
        for row in read_events(path)
    ]


def _measurement_offsets(path: Path) -> list[float]:
    return [
        float(row["time_offset_s"])
        for row in read_events(path)
        if float(row["time_offset_s"]) >= WARMUP_SECONDS
    ]


def _verify_arm_invariants(source: Path, arms: dict[str, Path]) -> dict[str, Any]:
    base_signature = _signature(source / "events.jsonl")
    native_offsets = _measurement_offsets(source / "events.jsonl")
    report: dict[str, Any] = {}
    for arm, directory in arms.items():
        manifest = validate_bundle(directory)
        if _signature(directory / "events.jsonl") != base_signature:
            raise ValueError(f"{arm} changed event identity, order, topic, payload, or gateway")
        offsets = _measurement_offsets(directory / "events.jsonl")
        if len(offsets) != len(native_offsets):
            raise ValueError(f"{arm} changed the measurement event count")
        if len(offsets) >= 2 and (
            not math.isclose(offsets[0], native_offsets[0], abs_tol=1e-12)
            or not math.isclose(offsets[-1], native_offsets[-1], abs_tol=1e-12)
        ):
            raise ValueError(f"{arm} changed the measurement endpoints")
        if arm.startswith("gap_permutation") and len(offsets) >= 2:
            native_gaps = sorted(b - a for a, b in zip(native_offsets, native_offsets[1:]))
            arm_gaps = sorted(b - a for a, b in zip(offsets, offsets[1:]))
            if len(native_gaps) != len(arm_gaps) or any(
                not math.isclose(a, b, abs_tol=1e-10)
                for a, b in zip(native_gaps, arm_gaps)
            ):
                raise ValueError(f"{arm} did not preserve the native measurement gap multiset")
        report[arm] = {
            "bundle_sha256": manifest["bundle_sha256"],
            "event_count": manifest["event_count"],
            "generation_age_valid": manifest.get("transformation", {}).get("generation_age_valid"),
        }
    return report


def _permutation_seed(campaign_id: str, seed: int, arm: str) -> int:
    digest = hashlib.sha256(
        f"{campaign_id}|{CONDITION}|{seed}|{arm}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big")


def _validate_prepared(root: Path) -> dict[str, Any]:
    index = _read_json(root / "prepared-index.json")
    if index.get("status") != "complete" or index.get("experiment") != "ex2":
        raise ValueError(f"prepared Experiment-2 source is incomplete: {root}")
    sources = index.get("sources", [])
    if len(sources) != EXPECTED_SOURCE_SEEDS:
        raise ValueError("prepared Experiment-2 source has the wrong source-seed count")
    for row in sources:
        seed = int(row["seed"])
        for arm in ARMS:
            directory = root / f"seed{seed:05d}" / arm / "model"
            manifest = validate_bundle(directory)
            expected = row.get("arms", {}).get(arm, {}).get("bundle_sha256")
            if expected != manifest.get("bundle_sha256"):
                raise ValueError(f"prepared bundle digest differs from its index: seed {seed} {arm}")
    return index


def discover_prepared() -> tuple[Path, dict[str, Any]]:
    if PREPARED_ROOT.is_dir():
        candidates = sorted(
            [path for path in PREPARED_ROOT.iterdir() if path.is_dir() and (path / "prepared-index.json").is_file()],
            key=lambda path: path.name,
        )
        for root in reversed(candidates):
            try:
                return root, _validate_prepared(root)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    raise ValueError(
        "no complete prepared Experiment-2 source cohort is local; run Ex2 preparation where Experiment 1 is stored, "
        "then rsync results/experiments/ex2-source/ to this checkout"
    )


def prepare_latest() -> dict[str, Any]:
    try:
        upstream = latest_complete_ex1()
    except ValueError:
        # A prepared cohort is intentionally transferable.  On Duckburg the full
        # Experiment-1 campaign need not be present once a verified cohort was
        # rsynced into the stable ex2-source path.
        root, index = discover_prepared()
        return {"status": "complete", "reused": True, "path": str(root), **index}
    campaign, design, rows = _verify_upstream(upstream)
    output = PREPARED_ROOT / str(campaign["campaign_id"])
    if (output / "prepared-index.json").is_file():
        index = _validate_prepared(output)
        return {"status": "complete", "reused": True, "path": str(output), **index}
    if output.exists():
        raise ValueError(f"refusing to overwrite incomplete prepared Experiment-2 source: {output}")
    output.mkdir(parents=True)

    prepared_rows = []
    for position, row in enumerate(rows, start=1):
        seed = int(row["seed"])
        source = (upstream / row["path"] / "model").resolve()
        source_manifest = validate_bundle(source)
        if source_manifest["bundle_sha256"] != row["bundle_sha256"]:
            raise ValueError(f"Experiment-1 bundle digest differs from index for seed {seed}")
        destinations = {
            arm: output / f"seed{seed:05d}" / arm / "model"
            for arm in ARMS
        }
        for arm, destination in destinations.items():
            variant = "gap_permutation" if arm.startswith("gap_permutation") else arm
            transform_bundle(
                source,
                destination,
                variant,
                seed=_permutation_seed(str(campaign["campaign_id"]), seed, arm),
                warmup_seconds=WARMUP_SECONDS,
            )
        report = _verify_arm_invariants(source, destinations)
        prepared_rows.append(
            {
                "seed": seed,
                "condition": CONDITION,
                "upstream_bundle_sha256": row["bundle_sha256"],
                "arms": report,
            }
        )
        print(f"Prepared {position}/{len(rows)}: {CONDITION} seed {seed}", flush=True)

    record = {
        "schema_version": 1,
        "status": "complete",
        "experiment": "ex2",
        "upstream_experiment": "ex1",
        "upstream_campaign_id": campaign["campaign_id"],
        "upstream_source_revision": campaign["source_revision"],
        "upstream_frozen_design_sha256": design["design_sha256"],
        "condition": CONDITION,
        "source_seed_count": len(prepared_rows),
        "timing_arms": list(ARMS),
        "warmup_seconds": WARMUP_SECONDS,
        "expected_confirmation_replays": len(prepared_rows) * len(ARMS) * 3,
        "sources": prepared_rows,
    }
    _write_json(output / "prepared-index.json", record)
    print(
        f"Experiment-2 source complete: {len(prepared_rows)} source seeds × {len(ARMS)} timing arms",
        flush=True,
    )
    return {"status": "complete", "reused": False, "path": str(output), **record}
