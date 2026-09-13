"""Paired Experiment-2 analysis; invoked internally by experiment.sh."""
from __future__ import annotations

import hashlib
import math
import random
import statistics
from pathlib import Path
from typing import Any

from .common import _read_json, _write_json


def _bootstrap(values: list[float], *, resamples: int, seed: int) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "ci95": [None, None]}
    observed = statistics.fmean(values)
    if len(values) == 1:
        return {"n": 1, "mean": observed, "ci95": [None, None]}
    rng = random.Random(seed)
    draws = sorted(
        statistics.fmean([values[rng.randrange(len(values))] for _ in values])
        for _ in range(resamples)
    )
    lo = int(0.025 * (len(draws) - 1))
    hi = int(0.975 * (len(draws) - 1))
    return {"n": len(values), "mean": observed, "ci95": [draws[lo], draws[hi]]}


def analysis(root: Path, *, manifest: dict[str, Any], environment: dict[str, Any] | None = None) -> dict[str, Any]:
    del environment
    destination = root / "analysis/summary.json"
    if destination.is_file():
        return _read_json(destination)

    frozen = _read_json(root / "frozen-design.json")
    expected = int(frozen["expected_replays"])
    records = [
        _read_json(path)
        for path in sorted((root / "runs").glob("*/run-record.json"))
    ]
    if len(records) != expected:
        raise RuntimeError(
            f"Experiment-2 analysis requires {expected} completed replays; found {len(records)}"
        )

    by_key = {
        (int(row["seed"]), str(row["load_level"]), str(row["timing_arm"])): row
        for row in records
    }
    if len(by_key) != expected:
        raise RuntimeError("Experiment-2 confirmation contains duplicate treatment cells")

    study = manifest["study"]
    statistics_plan = study["statistics"]
    outcomes = list(statistics_plan["principal_outcomes"])
    loads = ["below", "near", "above"]
    arms = list(frozen["timing_arms"])
    seeds = [int(value) for value in frozen["source_seeds"]]
    resamples = int(statistics_plan["bootstrap_resamples"])
    master_seed = int(statistics_plan["bootstrap_seed"])

    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "complete",
        "experiment": "ex2",
        "campaign_id": root.name,
        "deployment_hash": frozen["deployment_hash"],
        "experimental_unit": "source_seed",
        "runs_analyzed": len(records),
        "source_seeds": seeds,
        "load_levels_mbps": frozen["load_levels_mbps"],
        "timing_arms": arms,
        "principal_contrasts": {},
        "notes": [
            "Each source seed is one independent experimental unit within each load level.",
            "The two gap permutations are repeated matched controls and do not increase n.",
            "Seeds with invalid cross-host clock contracts or undefined outcomes are excluded only from the affected contrast/outcome.",
        ],
    }

    for load in loads:
        load_result: dict[str, Any] = {}
        for outcome in outcomes:
            native_minus_periodic: list[float] = []
            native_minus_gap_mean: list[float] = []
            included: list[int] = []
            excluded: list[dict[str, Any]] = []
            for seed in seeds:
                try:
                    rows = {arm: by_key[(seed, load, arm)] for arm in arms}
                except KeyError:
                    excluded.append({"seed": seed, "reason": "missing treatment cell"})
                    continue
                measurement = {arm: (rows[arm].get("measurement") or {}) for arm in arms}
                if not all(value.get("clock_contract_satisfied") is True for value in measurement.values()):
                    excluded.append({"seed": seed, "reason": "clock contract not satisfied in every matched arm"})
                    continue
                values = {arm: measurement[arm].get(outcome) for arm in arms}
                if any(value is None or not math.isfinite(float(value)) for value in values.values()):
                    excluded.append({"seed": seed, "reason": f"undefined {outcome}"})
                    continue
                native = float(values["native"])
                periodic = float(values["periodic"])
                gap_mean = statistics.fmean(
                    [float(values["gap_permutation_r1"]), float(values["gap_permutation_r2"])]
                )
                native_minus_periodic.append(native - periodic)
                native_minus_gap_mean.append(native - gap_mean)
                included.append(seed)

            digest = hashlib.sha256(
                f"{master_seed}|{root.name}|{load}|{outcome}".encode("utf-8")
            ).digest()
            local_seed = int.from_bytes(digest[:8], "big")
            load_result[outcome] = {
                "native_minus_periodic": _bootstrap(
                    native_minus_periodic,
                    resamples=resamples,
                    seed=local_seed,
                ),
                "native_minus_mean_gap_permutation": _bootstrap(
                    native_minus_gap_mean,
                    resamples=resamples,
                    seed=local_seed ^ 0x5A5A5A5A,
                ),
                "included_source_seeds": included,
                "excluded": excluded,
                "estimand": "paired mean difference across source seeds",
                "direction": "positive means native timing is worse because lower is better",
            }
        result["principal_contrasts"][load] = load_result

    _write_json(destination, result)
    return result
