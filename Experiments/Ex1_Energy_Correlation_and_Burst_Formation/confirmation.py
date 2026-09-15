"""Execute the frozen Experiment 1 v2 confirmation campaign."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from synthran.workload.bundle import validate_bundle
from synthran.workload.trace import implementation_fingerprint

from . import campaign, freeze

ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _current_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _verify_frozen_implementation(design: dict[str, Any]) -> None:
    current_revision = _current_revision()
    if current_revision != design["source_revision"]:
        raise ValueError(
            "source revision changed after the confirmation design was frozen; "
            "start a new qualified campaign instead of mixing implementations"
        )
    if implementation_fingerprint() != design["implementation"]:
        raise ValueError(
            "SynthRAN implementation/dependency fingerprint differs from the frozen design"
        )
    for relative, expected in design["experiment_source_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"experiment source differs from frozen design: {relative}")


def build_tasks(campaign_root: str | Path, design: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path(campaign_root).resolve()
    confirmation = design["confirmation"]
    sensor_count = int(confirmation["sensor_count"])
    tasks = []
    for condition in confirmation["condition_order"]:
        energy = confirmation["conditions"][condition]
        for seed in confirmation["seeds"]:
            name = f"{condition}-seed{int(seed):05d}"
            tasks.append(
                {
                    "campaign_root": str(root),
                    "phase": "confirmation",
                    "relative_root": ".",
                    "name": name,
                    "condition": condition,
                    "sensor_count": sensor_count,
                    "seed": int(seed),
                    "energy": energy,
                }
            )
    names = [task["name"] for task in tasks]
    if len(names) != len(set(names)):
        raise ValueError("confirmation task identities are not unique")
    return tasks


def _validate_existing_index(root: Path, design: dict[str, Any]) -> dict[str, Any] | None:
    path = root / "runs/index.json"
    if not path.is_file():
        return None
    value = campaign._read_json(path)
    if value.get("frozen_design_sha256") != design["design_sha256"]:
        raise ValueError("existing confirmation index belongs to a different frozen design")
    if int(value.get("runs_valid", -1)) != int(value.get("runs_expected", -2)):
        raise ValueError("existing confirmation index is incomplete")
    for row in value.get("runs", []):
        bundle = root / row["path"] / "model"
        manifest = validate_bundle(bundle)
        if manifest["bundle_sha256"] != row["bundle_sha256"]:
            raise ValueError(f"confirmation bundle identity changed: {row['name']}")
    return value


def run(campaign_root: str | Path) -> dict[str, Any]:
    root = Path(campaign_root).resolve()
    design = freeze.validate(campaign._read_json(root / "frozen-design.json"))
    _verify_frozen_implementation(design)
    existing = _validate_existing_index(root, design)
    if existing is not None:
        return existing

    tasks = build_tasks(root, design)
    expected = len(design["confirmation"]["condition_order"]) * len(
        design["confirmation"]["seeds"]
    )
    if len(tasks) != expected:
        raise ValueError("confirmation task count differs from the frozen treatment matrix")

    records = campaign.parallel_map(campaign._run_task, tasks)
    rows = []
    for task, record in zip(tasks, records):
        relative = Path("runs") / task["name"]
        manifest = validate_bundle(root / relative / "model")
        rows.append(
            {
                "name": task["name"],
                "condition": task["condition"],
                "seed": task["seed"],
                "path": str(relative),
                "bundle_sha256": manifest["bundle_sha256"],
                "resumed": bool(record["resumed"]),
            }
        )
    index = {
        "schema_version": 1,
        "status": "complete",
        "phase": "confirmation",
        "frozen_design_sha256": design["design_sha256"],
        "experimental_unit": design["confirmation"]["experimental_unit"],
        "sensor_count": int(design["confirmation"]["sensor_count"]),
        "conditions": list(design["confirmation"]["condition_order"]),
        "seeds": list(design["confirmation"]["seeds"]),
        "runs_expected": expected,
        "runs_valid": len(rows),
        "runs": rows,
    }
    if index["runs_valid"] != index["runs_expected"]:
        raise ValueError("confirmation completed without the full frozen cohort")
    campaign._write_json(root / "runs/index.json", index)
    print(
        f"Confirmation complete: {index['runs_valid']}/{index['runs_expected']} "
        "immutable bundles valid"
    )
    return index
