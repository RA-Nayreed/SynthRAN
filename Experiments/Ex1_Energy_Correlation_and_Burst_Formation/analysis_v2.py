"""Prespecified analysis for the Experiment 1 v2 confirmation cohort."""

from __future__ import annotations

import csv
import hashlib
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from synthran.workload.bundle import validate_bundle

from . import campaign, confirmation, freeze


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return campaign._read_jsonl(path)


def _finite_mean(values: list[float | None]) -> float | None:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return statistics.fmean(finite) if finite else None


def _pearson(left: list[float], right: list[float]) -> float | None:
    count = min(len(left), len(right))
    if count < 2:
        return None
    a, b = left[:count], right[:count]
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    da = [value - ma for value in a]
    db = [value - mb for value in b]
    denominator = math.sqrt(
        sum(value * value for value in da) * sum(value * value for value in db)
    )
    if denominator == 0:
        return None
    return sum(x * y for x, y in zip(da, db)) / denominator


def _pairwise_power_correlation(bundle: Path, warmup_s: float) -> float | None:
    series = []
    for path in sorted((bundle / "ambient_iot/energy-inputs").glob("*.csv")):
        values = []
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if float(row["time_s"]) >= warmup_s:
                    values.append(float(row["power_w"]))
        if values:
            series.append(values)
    correlations = []
    for left in range(len(series)):
        for right in range(left + 1, len(series)):
            value = _pearson(series[left], series[right])
            if value is not None:
                correlations.append(value)
    return _finite_mean(correlations)


def _event_offsets(bundle: Path, warmup_s: float, end_s: float) -> list[float]:
    return sorted(
        float(row["decode_time_s"])
        for row in _read_jsonl(bundle / "events.jsonl")
        if warmup_s <= float(row["decode_time_s"]) < end_s
    )


def _window_counts(
    offsets: list[float], start_s: float, end_s: float, width_s: float
) -> list[int]:
    if width_s <= 0 or end_s <= start_s:
        raise ValueError("analysis window width and horizon must be positive")
    count = max(1, math.ceil((end_s - start_s) / width_s))
    bins = [0] * count
    for value in offsets:
        if start_s <= value < end_s:
            index = min(count - 1, int((value - start_s) / width_s))
            bins[index] += 1
    return bins


def _fano(counts: list[int]) -> float | None:
    if not counts:
        return None
    mean = statistics.fmean(counts)
    return statistics.pvariance(counts) / mean if mean > 0 else None


def _gap_cv(offsets: list[float]) -> float | None:
    gaps = [right - left for left, right in zip(offsets, offsets[1:])]
    if not gaps:
        return None
    mean = statistics.fmean(gaps)
    return statistics.pstdev(gaps) / mean if mean > 0 else None


def _lag_autocorrelation(counts: list[int], lag: int) -> float | None:
    if lag <= 0 or len(counts) <= lag:
        return None
    return _pearson(
        [float(value) for value in counts[:-lag]],
        [float(value) for value in counts[lag:]],
    )


def _burst_stats(offsets: list[float], gap_threshold_s: float) -> dict[str, float | int | None]:
    if gap_threshold_s <= 0:
        raise ValueError("burst gap threshold must be positive")
    if not offsets:
        return {
            "burst_count": 0,
            "burst_size_mean": None,
            "burst_size_max": 0,
            "burst_duration_s_mean": None,
            "burst_duration_s_max": None,
        }
    bursts: list[list[float]] = [[offsets[0]]]
    for value in offsets[1:]:
        if value - bursts[-1][-1] <= gap_threshold_s:
            bursts[-1].append(value)
        else:
            bursts.append([value])
    sizes = [len(group) for group in bursts]
    durations = [group[-1] - group[0] for group in bursts]
    return {
        "burst_count": len(bursts),
        "burst_size_mean": statistics.fmean(sizes),
        "burst_size_max": max(sizes),
        "burst_duration_s_mean": statistics.fmean(durations),
        "burst_duration_s_max": max(durations),
    }


def _activation_sync_fraction(
    bundle: Path, warmup_s: float, end_s: float, window_s: float
) -> float | None:
    transitions = _read_jsonl(bundle / "ambient_iot/transitions.jsonl")
    by_node: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in transitions:
        by_node[int(row["node_id"])].append(row)
    onsets: list[tuple[int, float]] = []
    for node, rows in by_node.items():
        rows.sort(key=lambda row: float(row["time_ms"]))
        active = False
        for row in rows:
            when = float(row["time_ms"]) / 1000.0
            next_active = bool(row["active"])
            if warmup_s <= when < end_s and next_active and not active:
                onsets.append((node, when))
            active = next_active
    if not onsets:
        return None
    bins: dict[int, set[int]] = defaultdict(set)
    for node, when in onsets:
        bins[int((when - warmup_s) / window_s)].add(node)
    synchronized = sum(
        1 for node, when in onsets if len(bins[int((when - warmup_s) / window_s)]) >= 2
    )
    return synchronized / len(onsets)


def _run_metrics(bundle: Path, base: dict[str, Any], design: dict[str, Any]) -> dict[str, Any]:
    measurement = design["model_contract"]["measurement"]
    statistics_plan = design["statistics"]
    warmup = float(measurement["warmup_seconds"])
    end = float(measurement["duration_seconds"])
    fano_window = float(statistics_plan["fano_window_seconds"])
    peak_window = float(statistics_plan["peak_window_seconds"])
    lag = int(statistics_plan["count_autocorrelation_lag_windows"])
    offsets = _event_offsets(bundle, warmup, end)
    fano_counts = _window_counts(offsets, warmup, end, fano_window)
    peak_counts = _window_counts(offsets, warmup, end, peak_window)
    return {
        "active_fraction": float(base["active_fraction"]),
        "realized_power_correlation": _pairwise_power_correlation(bundle, warmup),
        "activation_sync_fraction": _activation_sync_fraction(
            bundle,
            warmup,
            end,
            float(statistics_plan["activation_sync_window_seconds"]),
        ),
        "generated_rate_per_s": float(base["generated_rate_per_s"]),
        "transmit_rate_per_s": float(base["transmit_rate_per_s"]),
        "decode_rate_per_s": float(base["decode_rate_per_s"]),
        "suppression_fraction": float(base["suppression_fraction"]),
        "collision_exposure": float(base["collision_exposure"]),
        "jain_decode_fairness": float(base["jain_decode_fairness"]),
        "fano": _fano(fano_counts),
        "gap_cv": _gap_cv(offsets),
        "count_autocorrelation_lag1": _lag_autocorrelation(fano_counts, lag),
        "peak_window_count": max(peak_counts) if peak_counts else 0,
        "decoded_events": len(offsets),
        **_burst_stats(offsets, float(statistics_plan["burst_gap_seconds"])),
    }


def _bootstrap_ci(
    differences: list[float], *, resamples: int, seed: int
) -> dict[str, Any]:
    if not differences:
        return {"n_pairs": 0, "mean_difference": None, "ci95": [None, None]}
    observed = statistics.fmean(differences)
    if len(differences) == 1 or resamples <= 1:
        return {
            "n_pairs": len(differences),
            "mean_difference": observed,
            "ci95": [observed, observed],
        }
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        sample = [differences[rng.randrange(len(differences))] for _ in differences]
        values.append(statistics.fmean(sample))
    values.sort()
    low_index = int(0.025 * (len(values) - 1))
    high_index = int(0.975 * (len(values) - 1))
    return {
        "n_pairs": len(differences),
        "mean_difference": observed,
        "ci95": [values[low_index], values[high_index]],
    }


def _paired_comparisons(records: list[dict[str, Any]], design: dict[str, Any]) -> dict[str, Any]:
    by_condition_seed = {
        (row["condition"], int(row["seed"])): row for row in records
    }
    metrics = (
        "realized_power_correlation",
        "activation_sync_fraction",
        "decode_rate_per_s",
        "collision_exposure",
        "fano",
        "gap_cv",
        "count_autocorrelation_lag1",
        "peak_window_count",
        "burst_size_mean",
    )
    plan = design["statistics"]
    result: dict[str, Any] = {}
    for regime in ("low", "knee", "high"):
        common = f"{regime}-common"
        independent = f"{regime}-independent"
        regime_result = {}
        for metric in metrics:
            differences = []
            for seed in design["confirmation"]["seeds"]:
                left = by_condition_seed[(common, int(seed))][metric]
                right = by_condition_seed[(independent, int(seed))][metric]
                if left is None or right is None:
                    continue
                left, right = float(left), float(right)
                if math.isfinite(left) and math.isfinite(right):
                    differences.append(left - right)
            digest = hashlib.sha256(
                f"{plan['paired_bootstrap_seed']}:{regime}:{metric}".encode()
            ).digest()
            seed_value = int.from_bytes(digest[:8], "big")
            regime_result[metric] = _bootstrap_ci(
                differences,
                resamples=int(plan["paired_bootstrap_resamples"]),
                seed=seed_value,
            )
        result[f"{common}_minus_{independent}"] = regime_result
    return result


def run(campaign_root: str | Path) -> dict[str, Any]:
    root = Path(campaign_root).resolve()
    destination = root / "analysis/summary.json"
    if destination.is_file():
        value = campaign._read_json(destination)
        design = freeze.validate(campaign._read_json(root / "frozen-design.json"))
        if value.get("frozen_design_sha256") != design["design_sha256"]:
            raise ValueError("existing analysis belongs to a different frozen design")
        return value

    design = freeze.validate(campaign._read_json(root / "frozen-design.json"))
    confirmation._verify_frozen_implementation(design)
    index = confirmation._validate_existing_index(root, design)
    if index is None:
        raise ValueError("analysis requires a complete confirmation index")

    records = []
    for row in index["runs"]:
        wrapper = root / row["path"]
        bundle = wrapper / "model"
        manifest = validate_bundle(bundle)
        if manifest["bundle_sha256"] != row["bundle_sha256"]:
            raise ValueError(f"bundle changed before analysis: {row['name']}")
        base = campaign._read_json(wrapper / "metrics.json")
        records.append(
            {
                "condition": row["condition"],
                "seed": int(row["seed"]),
                **_run_metrics(bundle, base, design),
            }
        )

    expected = len(design["confirmation"]["conditions"]) * len(
        design["confirmation"]["seeds"]
    )
    if len(records) != expected:
        raise ValueError("analysis did not receive the complete frozen cohort")

    metric_names = [
        key
        for key in records[0]
        if key not in {"condition", "seed"}
    ]
    condition_means = {}
    for condition in design["confirmation"]["condition_order"]:
        rows = [row for row in records if row["condition"] == condition]
        condition_means[condition] = {
            "n_runs": len(rows),
            "silent_runs": sum(int(row["decoded_events"]) == 0 for row in rows),
            **{
                name: _finite_mean([row[name] for row in rows])
                for name in metric_names
            },
        }

    result = {
        "schema_version": 1,
        "status": "complete",
        "experiment": "ex1",
        "frozen_design_sha256": design["design_sha256"],
        "experimental_unit": design["confirmation"]["experimental_unit"],
        "runs_expected": expected,
        "runs_analyzed": len(records),
        "metric_definitions": {
            "realized_power_correlation": "mean pairwise Pearson correlation of post-warmup sensor energy-input series",
            "activation_sync_fraction": "fraction of activation onsets sharing the prespecified time bin with an onset from another sensor",
            "fano": "variance-to-mean ratio of decoded-event counts in prespecified windows",
            "gap_cv": "coefficient of variation of inter-decode gaps",
            "count_autocorrelation_lag1": "Pearson correlation between adjacent decoded-count windows",
            "peak_window_count": "maximum decoded-event count in a prespecified peak window",
            "burst": "consecutive decoded events separated by no more than the prespecified burst-gap threshold",
        },
        "condition_means": condition_means,
        "paired_common_minus_independent": _paired_comparisons(records, design),
    }
    campaign._write_json(root / "analysis/run-metrics.json", {"runs": records})
    campaign._write_json(destination, result)
    print(f"Analysis complete: {len(records)}/{expected} independent seed runs")
    return result
