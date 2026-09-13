"""Freeze the calibrated Experiment 1 v2 confirmation design."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from synthran.workload.trace import implementation_fingerprint

from . import campaign

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _design_digest(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "design_sha256"}
    return hashlib.sha256(_canonical(payload)).hexdigest()


def validate(value: dict[str, Any]) -> dict[str, Any]:
    expected = value.get("design_sha256")
    if not isinstance(expected, str) or _design_digest(value) != expected:
        raise ValueError("frozen design failed its integrity check")
    if value.get("schema_version") != 1 or value.get("experiment") != "ex1":
        raise ValueError("unsupported frozen Experiment 1 design")
    confirmation = value.get("confirmation", {})
    conditions = confirmation.get("conditions", {})
    required = {
        "always-powered",
        "low-independent",
        "low-common",
        "knee-independent",
        "knee-common",
        "high-independent",
        "high-common",
    }
    if set(conditions) != required:
        raise ValueError("frozen confirmation treatment matrix is incomplete")
    order = confirmation.get("condition_order", [])
    if len(order) != len(required) or set(order) != required:
        raise ValueError("frozen confirmation condition order is incomplete")
    seeds = confirmation.get("seeds", [])
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("frozen confirmation seeds must be unique and non-empty")
    return value


def _condition(mode: str, power: float, correlation: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "source": "lognormal",
        "mean_power_w": float(power),
        "correlation": correlation,
    }


def run(campaign_root: str | Path) -> dict[str, Any]:
    root = Path(campaign_root).resolve()
    destination = root / "frozen-design.json"
    if destination.is_file():
        return validate(campaign._read_json(destination))

    manifest = campaign._manifest()
    study = manifest["study"]
    power = campaign._read_json(root / "calibration/power/selection.json")
    population = campaign._read_json(root / "calibration/population/selection.json")
    if power.get("status") != "selected" or population.get("status") != "selected":
        raise ValueError("freeze requires completed power and population calibration")

    selected_power = power["selected"]
    low = float(selected_power["low"]["mean_power_w"])
    knee = float(selected_power["knee"]["mean_power_w"])
    high = float(selected_power["high"]["mean_power_w"])
    n_star = int(population["selected"]["sensor_count"])
    if not 0 < low < knee < high:
        raise ValueError("calibrated power regimes must be strictly ordered")
    if n_star <= 0:
        raise ValueError("calibrated population must be positive")

    seed_spec = study["confirmation"]["seeds"]
    seeds = list(range(int(seed_spec["first"]), int(seed_spec["last"]) + 1))
    if len(seeds) != int(seed_spec["count"]):
        raise ValueError("confirmation seed range does not match its declared count")
    calibration_seeds = {
        *(int(value) for value in study["power_calibration"]["seeds"]),
        *(int(value) for value in study["population_calibration"]["seeds"]),
    }
    overlap = calibration_seeds.intersection(seeds)
    if overlap:
        raise ValueError(
            "confirmation seeds overlap calibration seeds: "
            + ", ".join(str(value) for value in sorted(overlap))
        )

    condition_map = {
        "always-powered": _condition("always_powered", knee, "independent"),
        "low-independent": _condition("environmental", low, "independent"),
        "low-common": _condition("environmental", low, "common"),
        "knee-independent": _condition("environmental", knee, "independent"),
        "knee-common": _condition("environmental", knee, "common"),
        "high-independent": _condition("environmental", high, "independent"),
        "high-common": _condition("environmental", high, "common"),
    }
    declared = list(study["confirmation"]["conditions"])
    if set(declared) != set(condition_map):
        raise ValueError("manifest confirmation conditions do not match the primary design")

    template = campaign._template()
    model_contract = {
        "measurement": study["measurement"],
        "energy": study["energy"],
        "sensor": study["sensor"],
        "capacitor": template["model"].get("capacitor", {}),
        "controller": template["model"].get("controller", {}),
        "topology": template["model"].get("topology", {}),
        "propagation": template["model"].get("propagation", {}),
        "protocol": template["model"].get("protocol", {}),
        "receiver": template["model"].get("receiver", {}),
        "mqtt": template.get("mqtt", {}),
        "gateways": template.get("gateways", []),
    }
    source_files = [
        HERE / "experiment.yml",
        HERE / "scenario-template.yml",
        HERE / "campaign.py",
        HERE / "population_calibration.py",
        HERE / "freeze.py",
        HERE / "confirmation.py",
        HERE / "analysis_v2.py",
    ]
    campaign_state = campaign._read_json(root / "campaign.json")
    value: dict[str, Any] = {
        "schema_version": 1,
        "experiment": "ex1",
        "design_version": int(manifest["design_version"]),
        "campaign_id": campaign_state["campaign_id"],
        "source_revision": campaign_state["source_revision"],
        "calibration": {
            "power_selection_sha256": _file_sha256(
                root / "calibration/power/selection.json"
            ),
            "population_selection_sha256": _file_sha256(
                root / "calibration/population/selection.json"
            ),
            "selected_power_w": {"low": low, "knee": knee, "high": high},
            "sensor_count": n_star,
        },
        "model_contract": model_contract,
        "confirmation": {
            "experimental_unit": study["statistics"]["experimental_unit"],
            "sensor_count": n_star,
            "seeds": seeds,
            "condition_order": declared,
            "conditions": {name: condition_map[name] for name in declared},
        },
        "statistics": study["statistics"],
        "implementation": implementation_fingerprint(),
        "experiment_source_sha256": {
            str(path.relative_to(ROOT)): _file_sha256(path) for path in source_files
        },
    }
    value["design_sha256"] = _design_digest(value)
    validate(value)
    campaign._write_json(destination, value)
    print(
        f"Frozen confirmation design: N*={n_star}, "
        f"seeds={len(seeds)}, sha256={value['design_sha256'][:12]}…"
    )
    return value
