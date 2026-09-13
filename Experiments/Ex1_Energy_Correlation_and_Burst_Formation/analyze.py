"""Analyze frozen Experiment 1 campaigns through one entry point.

Use --output for an exploratory analysis in a separate directory. Without it,
run the frozen campaign analysis phase or read its retained completed result.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

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


def _pairwise_power_correlation(
    bundle: Path, warmup_s: float, end_s: float = math.inf
) -> float | None:
    series = []
    reference_times = None
    for path in sorted((bundle / "ambient_iot/energy-inputs").glob("*.csv")):
        values = []
        times = []
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if warmup_s <= float(row["time_s"]) < end_s:
                    values.append(float(row["power_w"]))
                    times.append(float(row["time_s"]))
        if not times or any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError("power correlation requires nonempty, strictly increasing time grids")
        if reference_times is not None and times != reference_times:
            raise ValueError("power correlation requires aligned sensor time grids")
        reference_times = times
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
    if not all(math.isfinite(v) for v in (start_s, end_s, width_s)) or width_s <= 0 or end_s <= start_s:
        raise ValueError("analysis window width and horizon must be positive")
    ratio = (end_s - start_s) / width_s
    if not math.isfinite(ratio) or not math.isclose(ratio, round(ratio), abs_tol=1e-9):
        raise ValueError("count windows must tile the measurement horizon without a partial bin")
    count = max(1, round(ratio))
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
    if not math.isfinite(window_s) or window_s <= 0:
        raise ValueError("activation window must be positive and finite")
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


def _run_metrics(bundle: Path, design: dict[str, Any]) -> dict[str, Any]:
    measurement = design["model_contract"]["measurement"]
    statistics_plan = design["statistics"]
    warmup = float(measurement["warmup_seconds"])
    end = float(measurement["duration_seconds"])
    fano_window = float(statistics_plan["fano_window_seconds"])
    peak_window = float(statistics_plan["peak_window_seconds"])
    lag = int(statistics_plan["count_autocorrelation_lag_windows"])
    if not 0 <= warmup < end:
        raise ValueError("measurement warm-up must lie inside the run horizon")
    for relative in ("events.jsonl", "ambient_iot/transitions.jsonl", "ambient_iot/node-tx.jsonl",
                     "ambient_iot/bs-rx.jsonl", "ambient_iot/sensing-opportunities.jsonl"):
        if not (bundle / relative).is_file():
            raise ValueError(f"missing required analysis evidence: {relative}")
    if len(list((bundle / "ambient_iot/energy-inputs").glob("*.csv"))) != int(design["confirmation"]["sensor_count"]):
        raise ValueError("energy trace population differs from frozen design")
    offsets = _event_offsets(bundle, warmup, end)
    # Recompute from raw evidence; wrapper metrics are not bundle-hashed evidence.
    counts = campaign._measurement_counts(bundle, warmup, end)
    horizon = end - warmup
    fano_counts = _window_counts(offsets, warmup, end, fano_window)
    peak_counts = _window_counts(offsets, warmup, end, peak_window)
    bursts = _burst_stats(offsets, float(statistics_plan["burst_gap_seconds"]))
    return {
        "active_fraction": campaign._active_fraction(bundle, warmup, end),
        "realized_power_correlation": _pairwise_power_correlation(bundle, warmup, end),
        "activation_sync_fraction": _activation_sync_fraction(
            bundle,
            warmup,
            end,
            float(statistics_plan["activation_sync_window_seconds"]),
        ),
        "generated_rate_per_s": counts["generated"] / horizon,
        "transmit_rate_per_s": counts["transmitted"] / horizon,
        "decode_rate_per_s": len(offsets) / horizon,
        "suppression_fraction": counts["suppressed"] / counts["opportunities"] if counts["opportunities"] else None,
        "collision_exposure": counts["collision_losses"] / counts["transmitted"] if counts["transmitted"] else None,
        "jain_decode_fairness": counts["jain_decode_fairness"] if offsets else None,
        "silent_run": int(not offsets),
        "empty_window_fraction": sum(value == 0 for value in fano_counts) / len(fano_counts),
        "longest_observed_no_decode_interval_s": max(
            right - left for left, right in zip([warmup, *offsets], [*offsets, end])
        ),
        "single_gap_connected_component": int(bool(offsets) and bursts["burst_count"] == 1),
        "fano": _fano(fano_counts),
        "gap_cv": _gap_cv(offsets),
        "count_autocorrelation_lag1": _lag_autocorrelation(fano_counts, lag),
        "peak_window_count": max(peak_counts) if peak_counts else 0,
        "decoded_events": len(offsets),
        **bursts,
    }


def _bootstrap_ci(
    differences: list[float], *, resamples: int, seed: int
) -> dict[str, Any]:
    if not differences:
        return {"n_pairs": 0, "mean_difference": None, "ci95": [None, None]}
    observed = statistics.fmean(differences)
    if len(differences) == 1:
        return {
            "n_pairs": len(differences),
            "mean_difference": observed,
            "ci95": [None, None],
        }
    if resamples < 2:
        raise ValueError("bootstrap requires at least two resamples")
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
    _validate_cohort(records, design)
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
        "active_fraction",
        "generated_rate_per_s",
        "transmit_rate_per_s",
        "silent_run",
        "empty_window_fraction",
        "longest_observed_no_decode_interval_s",
    )
    plan = design["statistics"]
    result: dict[str, Any] = {}
    for regime in ("low", "knee", "high"):
        common = f"{regime}-common"
        independent = f"{regime}-independent"
        regime_result = {}
        for metric in metrics:
            differences = []
            excluded_seeds = []
            for seed in design["confirmation"]["seeds"]:
                left = by_condition_seed[(common, int(seed))][metric]
                right = by_condition_seed[(independent, int(seed))][metric]
                if left is None or right is None:
                    excluded_seeds.append(int(seed))
                    continue
                left, right = float(left), float(right)
                if math.isfinite(left) and math.isfinite(right):
                    differences.append(left - right)
                else:
                    excluded_seeds.append(int(seed))
            digest = hashlib.sha256(
                f"{plan['paired_bootstrap_seed']}:{regime}:{metric}".encode()
            ).digest()
            seed_value = int.from_bytes(digest[:8], "big")
            regime_result[metric] = _bootstrap_ci(
                differences,
                resamples=int(plan["paired_bootstrap_resamples"]),
                seed=seed_value,
            )
            regime_result[metric].update({
                "n_pairs_expected": len(design["confirmation"]["seeds"]),
                "excluded_seeds": excluded_seeds,
                "estimand": "mean within-seed difference among pairs with both values defined",
            })
        result[f"{common}_minus_{independent}"] = regime_result
    return result


def _validate_cohort(records: list[dict[str, Any]], design: dict[str, Any]) -> None:
    expected = {
        (condition, int(seed))
        for condition in design["confirmation"]["condition_order"]
        for seed in design["confirmation"]["seeds"]
    }
    observed = [(row["condition"], int(row["seed"])) for row in records]
    if len(observed) != len(set(observed)) or set(observed) != expected:
        raise ValueError("analysis requires each frozen condition/seed exactly once")


def _condition_summaries(records: list[dict[str, Any]], design: dict[str, Any]) -> dict[str, Any]:
    _validate_cohort(records, design)
    names = [name for name in records[0] if name not in {"condition", "seed"}]
    result = {}
    for condition in design["confirmation"]["condition_order"]:
        rows = [row for row in records if row["condition"] == condition]
        result[condition] = {
            "n_runs": len(rows),
            "silent_runs": sum(row["decoded_events"] == 0 for row in rows),
            **{name: _finite_mean([row[name] for row in rows]) for name in names},
            "metric_sample_sizes": {
                name: {
                    "n_valid": sum(row[name] is not None and math.isfinite(float(row[name])) for row in rows),
                    "n_undefined": sum(row[name] is None or not math.isfinite(float(row[name])) for row in rows),
                }
                for name in names
            },
        }
    return result


def run(campaign_root: str | Path, output: str | Path | None = None) -> dict[str, Any]:
    if output is not None:
        return _analyze_retained(campaign_root, output)
    root = Path(campaign_root).resolve()
    destination = root / "analysis/summary.json"
    if destination.is_file():
        value = campaign._read_json(destination)
        design = freeze.validate(campaign._read_json(root / "frozen-design.json"))
        if value.get("frozen_design_sha256") != design["design_sha256"]:
            raise ValueError("existing analysis belongs to a different frozen design")
        _validate_cohort(campaign._read_json(root / "analysis/run-metrics.json")["runs"], design)
        if value.get("status") != "complete":
            raise ValueError("existing analysis is incomplete")
        if value.get("schema_version") == 1:
            print("Preserving original schema-1 analysis; use analyze --output for updated diagnostics")
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
        records.append(
            {
                "condition": row["condition"],
                "seed": int(row["seed"]),
                **_run_metrics(bundle, design),
            }
        )

    expected = len(design["confirmation"]["conditions"]) * len(
        design["confirmation"]["seeds"]
    )
    if len(records) != expected:
        raise ValueError("analysis did not receive the complete frozen cohort")

    condition_means = _condition_summaries(records, design)

    result = {
        "schema_version": 2,
        "status": "complete",
        "experiment": "ex1",
        "frozen_design_sha256": design["design_sha256"],
        "experimental_unit": design["confirmation"]["experimental_unit"],
        "runs_expected": expected,
        "runs_analyzed": len(records),
        "interpretation": {
            "scope": "simulated decoding, not downstream transport delivery",
            "missing_values": "undefined metrics stay null; report silence separately and use metric-specific denominators",
            "burst": "gap-connected components, not an ordinal burstiness score; continuous traffic can form one horizon-spanning component",
            "uncertainty": "pointwise percentile bootstrap intervals over source-seed pairs; no multiplicity adjustment",
            "silence": "longest observed interval includes boundary-censored leading and trailing intervals; not a complete outage duration",
            "rates": "stage-specific timestamp windows, not a matched generation cohort delivery probability",
        },
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


def _validate_source(bundle: Path, row: dict, design: dict) -> dict:
    manifest = validate_bundle(bundle)
    frozen = design["confirmation"]
    measurement = design["model_contract"]["measurement"]
    if (manifest["bundle_sha256"] != row["bundle_sha256"] or manifest["seed"] != int(row["seed"])
            or manifest["duration_seconds"] != measurement["duration_seconds"]
            or manifest["implementation"] != design["implementation"]
            or manifest.get("transformation", {}).get("variant", "native") != "native"):
        raise ValueError("bundle identity or measurement contract differs from frozen confirmation")
    # The wrapper run-spec is not hashed by the source manifest. Check the
    # checksum-validated resolved scenario as the authority for treatment identity.
    scenario = yaml.safe_load((bundle / "resolved-scenario.yml").read_text(encoding="utf-8"))
    model = scenario["model"]
    expected_energy = {**design["model_contract"]["energy"], **frozen["conditions"][row["condition"]]}
    if (model["seed"] != int(row["seed"]) or model["duration_seconds"] != measurement["duration_seconds"]
            or len(scenario["devices"]) != frozen["sensor_count"]
            or any(model["energy"].get(key) != value for key, value in expected_energy.items())):
        raise ValueError("resolved scenario differs from frozen treatment")
    required = {"events.jsonl", "ambient_iot/sample-events.jsonl", "ambient_iot/transitions.jsonl",
                "ambient_iot/node-tx.jsonl", "ambient_iot/bs-rx.jsonl", "ambient_iot/sensing-opportunities.jsonl"}
    energy_names = {f"ambient_iot/energy-inputs/{device}.csv" for device in scenario["devices"]}
    if not (required | energy_names).issubset(manifest["files"]):
        raise ValueError("analysis evidence is not covered by the source manifest")
    return manifest


def _energy_integral(path: Path, start: float, end: float) -> float:
    """Integrate a hold-interpolated input, clipping both measurement boundaries."""
    with path.open(encoding="utf-8", newline="") as stream:
        samples = [(float(r["time_s"]), float(r["power_w"])) for r in csv.DictReader(stream)]
    if not samples or samples[0][0] > start or samples[-1][0] < end:
        raise ValueError(f"energy samples do not cover measurement window: {path.name}")
    if any(not math.isfinite(t) or not math.isfinite(p) or p < 0 for t, p in samples):
        raise ValueError(f"invalid energy sample: {path.name}")
    if any(b[0] <= a[0] for a, b in zip(samples, samples[1:])):
        raise ValueError(f"energy timestamps must strictly increase: {path.name}")
    return sum(
        power * max(0.0, min(next_time, end) - max(time, start))
        for (time, power), (next_time, _) in zip(samples, samples[1:])
    )


def _diagnostics(bundle: Path, design: dict) -> dict:
    measurement = design["model_contract"]["measurement"]
    start, end = float(measurement["warmup_seconds"]), float(measurement["duration_seconds"])
    duration = end - start
    if design["model_contract"]["energy"]["interpolation"] != "hold":
        raise ValueError("realized energy integration currently requires hold interpolation")
    energy_paths = sorted((bundle / "ambient_iot/energy-inputs").glob("*.csv"))
    if len(energy_paths) != int(design["confirmation"]["sensor_count"]):
        raise ValueError("energy trace population differs from frozen design")
    energies = {path.stem: _energy_integral(path, start, end) for path in energy_paths}
    events = campaign._read_jsonl(bundle / "events.jsonl")
    measured = [row for row in events if start <= float(row["decode_time_s"]) < end]
    service = Counter(row["device"] for row in measured)
    if set(service) - set(energies):
        raise ValueError("decoded sensor absent from energy trace population")
    per_sensor = [
        {"device": device, "input_energy_j": energy, "mean_input_power_w": energy / duration,
         "decoded_events": service[device], "zero_delivery": service[device] == 0}
        for device, energy in energies.items()
    ]

    # Classify the generation cohort by event identity, not differences between
    # counts selected using different stage timestamps.
    if not (bundle / "ambient_iot/sample-events.jsonl").is_file():
        raise ValueError("missing required sample lineage evidence")
    samples = campaign._read_jsonl(bundle / "ambient_iot/sample-events.jsonl")
    generated = {}
    lost_energy = set()
    for row in samples:
        time = float(row["time_ms"]) / 1000.0
        if row["kind"] == "generated" and start <= time < end:
            if row["event_id"] in generated:
                raise ValueError("duplicate generated event identity")
            generated[row["event_id"]] = time
        if row["kind"] == "sample_lost_energy" and time < end:
            lost_energy.add(row["event_id"])
    tx = {row["event_id"] for row in campaign._read_jsonl(bundle / "ambient_iot/node-tx.jsonl")
          if float(row["start_ms"]) < end * 1000}
    decoded = {row["event_id"]: row for row in measured}
    receptions = defaultdict(set)
    for row in campaign._read_jsonl(bundle / "ambient_iot/bs-rx.jsonl"):
        if float(row["end_ms"]) < end * 1000:
            receptions[row["event_id"]].add(row["outcome"])
    outcomes = Counter()
    latencies = []
    for event_id, when in generated.items():
        if event_id in decoded:
            outcome = "decoded_by_horizon"
            latency = float(decoded[event_id]["decode_time_s"]) - when
            if latency < 0:
                raise ValueError("decode precedes generation")
            latencies.append(latency)
        elif event_id in lost_energy:
            outcome = "sample_lost_energy"
        elif event_id not in tx:
            outcome = "not_transmitted_by_horizon"
        elif receptions[event_id]:
            outcome = "receiver_outcomes:" + ",".join(sorted(receptions[event_id]))
        else:
            outcome = "transmitted_without_completed_receiver_record"
        outcomes[outcome] += 1

    offsets = sorted(float(row["decode_time_s"]) for row in measured)
    # Sensitivity values are declared exploratory, not retroactively prespecified.
    sensitivity = {}
    for width in (0.1, 0.5, 1.0, 2.0, 5.0):
        if not math.isclose(duration / width, round(duration / width), abs_tol=1e-9):
            continue
        bins = _window_counts(offsets, start, end, width)
        sensitivity[str(width)] = {"fano": _fano(bins), "peak_count": max(bins),
                                   "empty_window_fraction": bins.count(0) / len(bins), "n_windows": len(bins)}
    return {
        "input_energy_j_per_sensor_mean": statistics.fmean(energies.values()),
        "realized_input_power_w_per_sensor_mean": statistics.fmean(energies.values()) / duration,
        "zero_delivery_sensor_fraction": sum(row["zero_delivery"] for row in per_sensor) / len(per_sensor),
        "per_sensor": per_sensor,
        "generation_cohort": {
            "generated": len(generated), "outcomes": dict(sorted(outcomes.items())),
            "decoded_fraction_by_horizon": outcomes["decoded_by_horizon"] / len(generated) if generated else None,
            "latency_s_mean_among_decoded": statistics.fmean(latencies) if latencies else None,
            "latency_s_max_among_decoded": max(latencies) if latencies else None,
            "decoded_in_window_generated_before_warmup": sum(float(row["generated_time_s"]) < start for row in measured),
        },
        "window_sensitivity_seconds": sensitivity,
        "burst_gap_sensitivity_seconds": {
            str(gap): _burst_stats(offsets, gap) for gap in (0.1, 0.25, 0.5, 1.0, 2.0)
        },
    }


def _analyze_retained(campaign_root: str | Path, output: str | Path) -> dict:
    root, destination = Path(campaign_root).resolve(), Path(output).resolve()
    if destination == root or destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError("reanalysis output must be separate from the source campaign")
    if destination.exists():
        raise ValueError("refusing to overwrite an existing reanalysis output")
    design = freeze.validate(campaign._read_json(root / "frozen-design.json"))
    index = campaign._read_json(root / "runs/index.json")
    if index.get("status") != "complete" or index.get("frozen_design_sha256") != design["design_sha256"]:
        raise ValueError("reanalysis requires a complete index bound to the frozen design")
    _validate_cohort(index["runs"], design)
    expected = len(index["runs"])
    if index.get("runs_valid") != expected or index.get("runs_expected") != expected:
        raise ValueError("confirmation index counts differ from frozen cohort")
    records, diagnostics, identities = [], [], []
    source_files = [Path(__file__), Path(campaign.__file__), Path(freeze.__file__),
                    Path(confirmation.__file__)]
    for row in index["runs"]:
        wrapper = (root / row["path"]).resolve()
        if not wrapper.is_relative_to(root / "runs"):
            raise ValueError("unsafe confirmation path")
        spec = campaign._read_json(wrapper / "run-spec.json")
        if (spec.get("condition") != row["condition"] or spec.get("seed") != int(row["seed"])
                or spec.get("sensor_count") != design["confirmation"]["sensor_count"]
                or spec.get("energy") != design["confirmation"]["conditions"][row["condition"]]):
            raise ValueError("run specification differs from frozen condition")
        bundle = wrapper / "model"
        manifest = _validate_source(bundle, row, design)
        identity = {"condition": row["condition"], "seed": int(row["seed"])}
        record = {**identity, **_run_metrics(bundle, design)}
        detail = _diagnostics(bundle, design)
        records.append(record)
        diagnostics.append({**identity, **detail})
        identities.append({**identity, "bundle_sha256": manifest["bundle_sha256"]})
        print(f"Analysis {len(records)}/{expected}: {row['condition']} seed {row['seed']}", flush=True)
    measurement = design["model_contract"]["measurement"]
    duration = measurement["duration_seconds"] - measurement["warmup_seconds"]
    result = {
        "schema_version": 1, "status": "complete", "analysis_class": "exploratory_reanalysis",
        "source_campaign_id": design["campaign_id"], "source_revision": design["source_revision"],
        "frozen_design_sha256": design["design_sha256"],
        "analysis_revision": confirmation._current_revision(),
        "analysis_python": sys.version,
        "analysis_source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files},
        "source_index_sha256": hashlib.sha256((root / "runs/index.json").read_bytes()).hexdigest(),
        "source_bundles": identities, "experimental_unit": "source_seed",
        "runs_analyzed": expected, "measurement_duration_s": duration,
        "measurement_correlation_times": duration / design["model_contract"]["energy"]["correlation_time_s"],
        "condition_means": _condition_summaries(records, design),
        "paired_common_minus_independent": _paired_comparisons(records, design),
        "interpretation": [
            "Exploratory reanalysis; original frozen analysis is preserved and is not reclassified as prespecified.",
            "Pointwise bootstrap intervals resample source seeds, not packets, sensors, or time windows; no multiplicity correction.",
            "Undefined metrics remain null; report valid sample sizes and silence alongside conditional metrics.",
            "Burst size measures gap-connected components; continuous traffic can be a single observation-spanning component.",
            "Longest observed no-decode interval includes censored boundaries; it is not an uncensored outage duration.",
            "Generation cohorts are followed only to the simulation horizon; undecoded cases are not automatically permanent losses.",
            "Input power is source energy, not capacitor-stored energy; always-powered mode bypasses energy gating.",
            "Results concern simulated decoding, not measured MQTT or 5G delivery.",
        ],
    }
    destination.mkdir(parents=True, exist_ok=False)
    campaign._write_json(destination / "run-metrics.json", {"runs": records})
    campaign._write_json(destination / "run-diagnostics.json", {"runs": diagnostics})
    campaign._write_json(destination / "summary.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="New directory for exploratory results; preserves the source campaign")
    args = parser.parse_args()
    run(args.campaign, args.output)


if __name__ == "__main__":
    main()
