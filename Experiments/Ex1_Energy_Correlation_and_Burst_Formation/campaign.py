#!/usr/bin/env python3
"""Experiment 1 v2 campaign phases.

This module is an internal study implementation used by ``experiment.sh`` via
``synthran.experiments``. Public tuning switches intentionally live in neither
place: the versioned experiment manifest is the scientific design contract.
"""

from __future__ import annotations

import copy
import csv
import itertools
import json
import math
import statistics
import time
import tracemalloc
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from synthran.archive import archive_run
from synthran.experiments import parallel_map
from synthran.workload.bundle import validate_bundle
from synthran.workload.trace import generate

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "experiment.yml"
TEMPLATE = HERE / "scenario-template.yml"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _manifest() -> dict[str, Any]:
    value = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("id") != "ex1":
        raise ValueError("invalid Experiment 1 manifest")
    if not isinstance(value.get("study"), dict):
        raise ValueError("Experiment 1 manifest requires study settings")
    return value


def _template() -> dict[str, Any]:
    value = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Experiment 1 scenario template must be a mapping")
    return value


def _scenario(
    manifest: dict[str, Any],
    *,
    sensor_count: int,
    seed: int,
    energy: dict[str, Any],
) -> dict[str, Any]:
    study = manifest["study"]
    measurement = study["measurement"]
    value = copy.deepcopy(_template())
    model = value["model"]
    model["seed"] = int(seed)
    model["duration_seconds"] = float(measurement["duration_seconds"])
    model["energy"] = {
        **model.get("energy", {}),
        **study["energy"],
        **energy,
    }
    sensor = dict(study.get("sensor", {}))
    sensor["sensing_interval_ms"] = float(measurement["sensing_interval_ms"])
    gateways = list(value.get("gateways", []))
    if not gateways:
        raise ValueError("scenario template requires at least one gateway")
    value["devices"] = {
        f"sensor{index:03d}": {
            **sensor,
            "gateway": gateways[(index - 1) % len(gateways)],
        }
        for index in range(1, int(sensor_count) + 1)
    }
    return value


def _active_fraction(bundle: Path, warmup_s: float, duration_s: float) -> float:
    rows = _read_jsonl(bundle / "ambient_iot/transitions.jsonl")
    by_node: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_node[int(row["node_id"])].append(row)
    start_ms, end_ms = warmup_s * 1000.0, duration_s * 1000.0
    fractions = []
    for node_rows in by_node.values():
        node_rows.sort(key=lambda item: float(item["time_ms"]))
        active = False
        cursor = start_ms
        active_ms = 0.0
        for row in node_rows:
            when = float(row["time_ms"])
            if when <= start_ms:
                active = bool(row["active"])
                continue
            if when >= end_ms:
                break
            if active:
                active_ms += when - cursor
            cursor = when
            active = bool(row["active"])
        if active and cursor < end_ms:
            active_ms += end_ms - cursor
        fractions.append(active_ms / (end_ms - start_ms))
    if not fractions:
        raise ValueError(f"no controller transitions in {bundle}")
    return statistics.fmean(fractions)


def _capacitor_statistics(bundle: Path, warmup_s: float) -> dict[str, float]:
    sensor_means: list[float] = []
    minimum = math.inf
    maximum = -math.inf
    for path in sorted((bundle / "ambient_iot/capacitor").glob("*.csv")):
        values = []
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if float(row["time_s"]) >= warmup_s:
                    values.append(float(row["voltage_v"]))
        if values:
            sensor_means.append(statistics.fmean(values))
            minimum = min(minimum, min(values))
            maximum = max(maximum, max(values))
    if not sensor_means:
        raise ValueError(f"no capacitor samples in {bundle}")
    return {
        "mean_voltage_v": statistics.fmean(sensor_means),
        "minimum_voltage_v": minimum,
        "maximum_voltage_v": maximum,
    }


def _measurement_counts(bundle: Path, warmup_s: float) -> dict[str, Any]:
    warmup_ms = warmup_s * 1000.0
    opportunities = [
        row
        for row in _read_jsonl(bundle / "ambient_iot/sensing-opportunities.jsonl")
        if float(row["time_ms"]) >= warmup_ms
    ]
    node_tx = [
        row
        for row in _read_jsonl(bundle / "ambient_iot/node-tx.jsonl")
        if float(row["start_ms"]) >= warmup_ms
    ]
    receptions = [
        row
        for row in _read_jsonl(bundle / "ambient_iot/bs-rx.jsonl")
        if float(row["start_ms"]) >= warmup_ms
    ]
    events = [
        row
        for row in _read_jsonl(bundle / "events.jsonl")
        if float(row["decode_time_s"]) >= warmup_s
    ]
    generated = sum(row.get("outcome") == "generated" for row in opportunities)
    suppressed = len(opportunities) - generated

    reception_groups: dict[tuple[int, float], list[dict[str, Any]]] = defaultdict(list)
    for row in receptions:
        reception_groups[(int(row["node_id"]), float(row["start_ms"]))].append(row)
    collision_losses = sum(
        bool(rows) and all(row.get("outcome") == "collision" for row in rows)
        for rows in reception_groups.values()
    )

    decoded_per_device: dict[str, int] = defaultdict(int)
    for row in events:
        decoded_per_device[str(row["device"])] += 1
    all_devices = {
        path.stem for path in (bundle / "ambient_iot/energy-inputs").glob("*.csv")
    }
    service = [decoded_per_device.get(name, 0) for name in sorted(all_devices)]
    squared = sum(value * value for value in service)
    fairness = (
        (sum(service) ** 2) / (len(service) * squared)
        if service and squared
        else 0.0
    )
    return {
        "opportunities": len(opportunities),
        "generated": generated,
        "suppressed": suppressed,
        "transmitted": len(node_tx),
        "decoded": len(events),
        "collision_losses": collision_losses,
        "decoded_per_device": dict(sorted(decoded_per_device.items())),
        "jain_decode_fairness": fairness,
    }


def _metrics(bundle: Path, measurement: dict[str, Any]) -> dict[str, Any]:
    warmup_s = float(measurement["warmup_seconds"])
    duration_s = float(measurement["duration_seconds"])
    window_s = duration_s - warmup_s
    if not 0 <= warmup_s < duration_s:
        raise ValueError("measurement warm-up must lie inside the run horizon")
    counts = _measurement_counts(bundle, warmup_s)
    capacitors = _capacitor_statistics(bundle, warmup_s)
    transmitted = counts["transmitted"]
    return {
        "measurement_window_seconds": [warmup_s, duration_s],
        "active_fraction": _active_fraction(bundle, warmup_s, duration_s),
        "generated_rate_per_s": counts["generated"] / window_s,
        "transmit_rate_per_s": transmitted / window_s,
        "decode_rate_per_s": counts["decoded"] / window_s,
        "suppression_fraction": (
            counts["suppressed"] / counts["opportunities"]
            if counts["opportunities"]
            else 0.0
        ),
        "collision_exposure": (
            counts["collision_losses"] / transmitted if transmitted else 0.0
        ),
        **counts,
        "capacitor": capacitors,
    }


def _spec_matches(path: Path, expected: dict[str, Any]) -> bool:
    try:
        return _read_json(path) == expected
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _archive_result(
    root: Path,
    destination: Path,
    manifest: dict[str, Any],
    phase: str,
    name: str,
) -> dict[str, Any]:
    settings = manifest.get("archive", {})
    if not bool(settings.get("enabled", False)):
        return {"archive_status": "disabled"}
    campaign_state = _read_json(root / "campaign.json")
    return archive_run(
        destination,
        settings=settings,
        campaign=campaign_state,
        phase=phase,
        run_id=name,
    )


def _run_task(task: dict[str, Any]) -> dict[str, Any]:
    manifest = _manifest()
    measurement = manifest["study"]["measurement"]
    root = Path(task["campaign_root"])
    phase = str(task["phase"])
    name = str(task["name"])
    destination = root / task["relative_root"] / "runs" / name
    spec = {
        "schema_version": 1,
        "phase": phase,
        "name": name,
        "condition": task.get("condition"),
        "sensor_count": int(task["sensor_count"]),
        "seed": int(task["seed"]),
        "energy": task["energy"],
    }

    if destination.exists():
        if not _spec_matches(destination / "run-spec.json", spec):
            raise ValueError(f"existing run specification differs: {destination}")
        validate_bundle(destination / "model")
        metrics_path = destination / "metrics.json"
        result = _read_json(metrics_path) if metrics_path.is_file() else _metrics(
            destination / "model", measurement
        )
        if not metrics_path.is_file():
            _write_json(metrics_path, result)
        archive = _archive_result(root, destination, manifest, phase, name)
        return {
            "name": name,
            "resumed": True,
            "spec": spec,
            "metrics": result,
            "archive": archive,
        }

    staging_root = root / ".staging" / phase
    staging_root.mkdir(parents=True, exist_ok=True)
    staging = staging_root / f"{name}-{task['seed']}-{int(time.time_ns())}"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        _write_json(staging / "run-spec.json", spec)
        scenario = _scenario(
            manifest,
            sensor_count=spec["sensor_count"],
            seed=spec["seed"],
            energy=spec["energy"],
        )
        scenario_path = staging / "scenario.yml"
        scenario_path.write_text(
            yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8"
        )
        tracemalloc.start()
        started = time.perf_counter()
        generate(scenario_path, staging / "model")
        elapsed = time.perf_counter() - started
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        validate_bundle(staging / "model")
        result = _metrics(staging / "model", measurement)
        result["runtime"] = {
            "wall_seconds": elapsed,
            "python_peak_bytes": int(peak_bytes),
        }
        _write_json(staging / "metrics.json", result)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(destination)
        archive = _archive_result(root, destination, manifest, phase, name)
        return {
            "name": name,
            "resumed": False,
            "spec": spec,
            "metrics": result,
            "archive": archive,
        }
    except BaseException:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        failed = root / "failed" / phase
        failed.mkdir(parents=True, exist_ok=True)
        target = failed / staging.name
        if staging.exists():
            staging.replace(target)
        raise


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot aggregate an empty metric")
    return statistics.fmean(values)


def _aggregate_power(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_power: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_power[float(record["spec"]["energy"]["mean_power_w"])].append(record)
    fields = (
        "active_fraction",
        "generated_rate_per_s",
        "transmit_rate_per_s",
        "decode_rate_per_s",
        "suppression_fraction",
        "collision_exposure",
        "jain_decode_fairness",
    )
    aggregates = []
    for power, rows in sorted(by_power.items()):
        entry: dict[str, Any] = {
            "mean_power_w": power,
            "runs": len(rows),
            "seeds": sorted(int(row["spec"]["seed"]) for row in rows),
        }
        for field in fields:
            values = [float(row["metrics"][field]) for row in rows]
            entry[field + "_mean"] = _mean(values)
            entry[field + "_sd"] = statistics.stdev(values) if len(values) > 1 else 0.0
        entry["capacitor_mean_voltage_v_mean"] = _mean(
            [float(row["metrics"]["capacitor"]["mean_voltage_v"]) for row in rows]
        )
        aggregates.append(entry)
    return aggregates


def _select_power_points(
    aggregates: list[dict[str, Any]], design: dict[str, Any]
) -> dict[str, Any]:
    targets = design["target_active_fraction"]
    acceptance = design["acceptance"]
    if len(aggregates) < 3:
        raise ValueError("power calibration requires at least three candidate powers")
    tolerance = float(acceptance["monotonic_tolerance"])
    active = [float(row["active_fraction_mean"]) for row in aggregates]
    for left, right in zip(active, active[1:]):
        if right + tolerance < left:
            raise ValueError(
                "power calibration active fraction is not monotonic within tolerance"
            )

    best = None
    for indices in itertools.combinations(range(len(aggregates)), 3):
        rows = [aggregates[index] for index in indices]
        score = sum(
            abs(float(row["active_fraction_mean"]) - float(targets[label]))
            for row, label in zip(rows, ("low", "knee", "high"))
        )
        candidate = (score, indices, rows)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    assert best is not None
    _, indices, rows = best
    chosen = dict(zip(("low", "knee", "high"), rows))
    low = float(chosen["low"]["active_fraction_mean"])
    knee = float(chosen["knee"]["active_fraction_mean"])
    high = float(chosen["high"]["active_fraction_mean"])
    failures = []
    if low > float(acceptance["low_max_active_fraction"]):
        failures.append("low regime is too active")
    if not (
        float(acceptance["knee_min_active_fraction"])
        <= knee
        <= float(acceptance["knee_max_active_fraction"])
    ):
        failures.append("knee regime is outside the accepted active-fraction band")
    if high < float(acceptance["high_min_active_fraction"]):
        failures.append("high regime is not sufficiently active")
    if not low < knee < high:
        failures.append("selected active fractions are not strictly ordered")
    if failures:
        raise ValueError("; ".join(failures))

    return {
        "schema_version": 1,
        "status": "selected",
        "definition": (
            "Choose three ordered candidate powers jointly minimizing absolute "
            "distance to the prespecified low/knee/high mean active-fraction targets, "
            "then enforce the prespecified acceptance bands."
        ),
        "targets": targets,
        "acceptance": acceptance,
        "selected_candidate_indices": list(indices),
        "selected": {
            label: {
                "mean_power_w": float(row["mean_power_w"]),
                "active_fraction_mean": float(row["active_fraction_mean"]),
            }
            for label, row in chosen.items()
        },
    }


def power_calibration(campaign_root: str | Path) -> dict[str, Any]:
    root = Path(campaign_root).resolve()
    qualification = _read_json(root / "qualification/qualification.json")
    if qualification.get("status") != "passed":
        raise ValueError("power calibration requires a passed qualification gate")
    manifest = _manifest()
    design = manifest["study"]["power_calibration"]
    output = root / "calibration/power"
    summary_path = output / "summary.json"
    selection_path = output / "selection.json"
    if summary_path.is_file() and selection_path.is_file():
        selection = _read_json(selection_path)
        if selection.get("status") != "selected":
            raise ValueError("existing power selection is not valid")
        return selection

    tasks = []
    for power in design["candidate_mean_power_w"]:
        for seed in design["seeds"]:
            name = f"p{round(float(power) * 1e6):07d}uw-seed{int(seed):05d}"
            tasks.append(
                {
                    "campaign_root": str(root),
                    "phase": "power-calibration",
                    "relative_root": "calibration/power",
                    "name": name,
                    "sensor_count": int(design["sensor_count"]),
                    "seed": int(seed),
                    "energy": {
                        "mode": "environmental",
                        "source": "lognormal",
                        "correlation": design["correlation"],
                        "mean_power_w": float(power),
                    },
                }
            )
    records = parallel_map(_run_task, tasks)
    aggregates = _aggregate_power(records)
    summary = {
        "schema_version": 1,
        "phase": "power-calibration",
        "candidate_mean_power_w": [float(value) for value in design["candidate_mean_power_w"]],
        "seeds": [int(value) for value in design["seeds"]],
        "sensor_count": int(design["sensor_count"]),
        "correlation": design["correlation"],
        "runs_expected": len(tasks),
        "runs_valid": len(records),
        "aggregates": aggregates,
        "runs": records,
    }
    selection = _select_power_points(aggregates, design)
    _write_json(summary_path, summary)
    _write_json(selection_path, selection)
    print(
        "Selected harvested-power regimes: "
        + ", ".join(
            f"{name}={value['mean_power_w'] * 1e6:g} µW"
            for name, value in selection["selected"].items()
        )
    )
    return selection


if __name__ == "__main__":
    raise SystemExit(
        "campaign.py is an internal Experiment 1 implementation; use ./experiment.sh"
    )
