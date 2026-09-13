"""Population-calibration phase for Experiment 1 v2."""

from __future__ import annotations

import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import campaign


def _aggregate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_count: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_count[int(record["spec"]["sensor_count"])].append(record)
    fields = (
        "active_fraction",
        "generated_rate_per_s",
        "transmit_rate_per_s",
        "decode_rate_per_s",
        "collision_exposure",
        "jain_decode_fairness",
    )
    rows = []
    for sensor_count, group in sorted(by_count.items()):
        entry: dict[str, Any] = {
            "sensor_count": sensor_count,
            "runs": len(group),
            "seeds": sorted(int(row["spec"]["seed"]) for row in group),
        }
        for field in fields:
            values = [float(row["metrics"][field]) for row in group]
            entry[field + "_mean"] = statistics.fmean(values)
            entry[field + "_sd"] = statistics.stdev(values) if len(values) > 1 else 0.0
        runtimes = [
            float(row["metrics"].get("runtime", {}).get("wall_seconds"))
            for row in group
            if row["metrics"].get("runtime", {}).get("wall_seconds") is not None
        ]
        peaks = [
            int(row["metrics"].get("runtime", {}).get("python_peak_bytes"))
            for row in group
            if row["metrics"].get("runtime", {}).get("python_peak_bytes") is not None
        ]
        entry["wall_seconds_mean"] = statistics.fmean(runtimes) if runtimes else None
        entry["python_peak_bytes_max"] = max(peaks) if peaks else None
        rows.append(entry)
    return rows


def _select_population(
    aggregates: list[dict[str, Any]], design: dict[str, Any]
) -> dict[str, Any]:
    if len(aggregates) < 3:
        raise ValueError("population calibration requires at least three candidates")
    target = float(design["target_collision_exposure"])
    lower, upper = (float(value) for value in design["accepted_collision_exposure"])
    minimum_relative_decode = float(design["minimum_relative_decode_rate"])
    maximum_decode = max(float(row["decode_rate_per_s_mean"]) for row in aggregates)
    if maximum_decode <= 0:
        raise ValueError("population calibration decoded no events at any candidate population")

    eligible = []
    for index, row in enumerate(aggregates):
        collision = float(row["collision_exposure_mean"])
        decode = float(row["decode_rate_per_s_mean"])
        relative_decode = decode / maximum_decode
        if lower <= collision <= upper and relative_decode >= minimum_relative_decode:
            eligible.append((abs(collision - target), index, relative_decode, row))
    if not eligible:
        raise ValueError(
            "population grid has no candidate inside the prespecified contention "
            "band while retaining the required relative decode rate"
        )
    _, index, relative_decode, selected = min(eligible, key=lambda item: (item[0], item[1]))
    if bool(design.get("require_interior", True)) and index in {0, len(aggregates) - 1}:
        raise ValueError(
            "selected population lies on a calibration-grid boundary; expand the grid "
            "before freezing N*"
        )
    return {
        "schema_version": 1,
        "status": "selected",
        "definition": (
            "Among candidates inside the prespecified collision-exposure band and "
            "retaining the required fraction of the best observed decode rate, choose "
            "the population closest to the target collision exposure."
        ),
        "target_collision_exposure": target,
        "accepted_collision_exposure": [lower, upper],
        "minimum_relative_decode_rate": minimum_relative_decode,
        "selected_candidate_index": index,
        "selected": {
            "sensor_count": int(selected["sensor_count"]),
            "collision_exposure_mean": float(selected["collision_exposure_mean"]),
            "decode_rate_per_s_mean": float(selected["decode_rate_per_s_mean"]),
            "relative_decode_rate": relative_decode,
            "jain_decode_fairness_mean": float(selected["jain_decode_fairness_mean"]),
        },
    }


def run(campaign_root: str | Path) -> dict[str, Any]:
    root = Path(campaign_root).resolve()
    power_selection = campaign._read_json(root / "calibration/power/selection.json")
    if power_selection.get("status") != "selected":
        raise ValueError("population calibration requires selected power regimes")
    manifest = campaign._manifest()
    design = manifest["study"]["population_calibration"]
    knee_power = float(power_selection["selected"]["knee"]["mean_power_w"])
    output = root / "calibration/population"
    summary_path = output / "summary.json"
    selection_path = output / "selection.json"
    if summary_path.is_file() and selection_path.is_file():
        selection = campaign._read_json(selection_path)
        if selection.get("status") != "selected":
            raise ValueError("existing population selection is not valid")
        return selection

    tasks = []
    for sensor_count in design["candidate_sensor_counts"]:
        for seed in design["seeds"]:
            name = f"n{int(sensor_count):04d}-seed{int(seed):05d}"
            tasks.append(
                {
                    "campaign_root": str(root),
                    "phase": "population-calibration",
                    "relative_root": "calibration/population",
                    "name": name,
                    "sensor_count": int(sensor_count),
                    "seed": int(seed),
                    "energy": {
                        "mode": "environmental",
                        "source": "lognormal",
                        "correlation": design["correlation"],
                        "mean_power_w": knee_power,
                    },
                }
            )
    records = campaign.parallel_map(campaign._run_task, tasks)
    aggregates = _aggregate(records)
    summary = {
        "schema_version": 1,
        "phase": "population-calibration",
        "knee_mean_power_w": knee_power,
        "candidate_sensor_counts": [int(value) for value in design["candidate_sensor_counts"]],
        "seeds": [int(value) for value in design["seeds"]],
        "correlation": design["correlation"],
        "runs_expected": len(tasks),
        "runs_valid": len(records),
        "aggregates": aggregates,
        "runs": records,
    }
    selection = _select_population(aggregates, design)
    campaign._write_json(summary_path, summary)
    campaign._write_json(selection_path, selection)
    print(
        "Selected contention population: "
        f"N*={selection['selected']['sensor_count']} "
        f"(collision={selection['selected']['collision_exposure_mean']:.3f})"
    )
    return selection
