#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_ROOT = ROOT / "results" / "exp1-energy-correlation"
DURATION_SECONDS = 60.0
WARMUP_SECONDS = 10.0
CONFIRMATION_SEEDS = tuple(range(1001, 1031))
CONDITIONS = (
    "always-powered",
    "low-independent",
    "low-common",
    "knee-independent",
    "knee-common",
    "high-independent",
    "high-common",
)


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def active_fraction(bundle: Path) -> float:
    rows = read_jsonl(bundle / "ambient_iot" / "transitions.jsonl")
    by_node: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_node[int(row["node_id"])].append(row)

    start_ms = WARMUP_SECONDS * 1000.0
    end_ms = DURATION_SECONDS * 1000.0
    values = []
    for node_rows in by_node.values():
        node_rows.sort(key=lambda row: float(row["time_ms"]))
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
        values.append(active_ms / (end_ms - start_ms))
    return statistics.fmean(values) if values else math.nan


def event_offsets(bundle: Path) -> list[float]:
    values = []
    for row in read_jsonl(bundle / "events.jsonl"):
        when = row.get("reader_decode_time_s", row.get("time_offset_s"))
        if when is not None and float(when) >= WARMUP_SECONDS:
            values.append(float(when))
    return sorted(values)


def gap_cv(offsets: list[float]) -> float:
    gaps = [later - earlier for earlier, later in zip(offsets, offsets[1:])]
    if not gaps:
        return math.nan
    avg = statistics.fmean(gaps)
    return statistics.pstdev(gaps) / avg if avg > 0 else math.nan


def fano_one_second(offsets: list[float]) -> float:
    bins = [0] * int(DURATION_SECONDS - WARMUP_SECONDS)
    for when in offsets:
        index = int(when - WARMUP_SECONDS)
        if 0 <= index < len(bins):
            bins[index] += 1
    avg = statistics.fmean(bins) if bins else 0.0
    return statistics.pvariance(bins) / avg if avg > 0 else math.nan


def pairwise_power_correlation(bundle: Path) -> float:
    series = []
    inputs = bundle / "ambient_iot" / "energy-inputs"
    for path in sorted(inputs.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as stream:
            series.append([float(row["power_w"]) for row in csv.DictReader(stream)])

    correlations = []
    for left in range(len(series)):
        for right in range(left + 1, len(series)):
            a = series[left]
            b = series[right]
            count = min(len(a), len(b))
            if count < 2:
                continue
            a = a[:count]
            b = b[:count]
            ma = statistics.fmean(a)
            mb = statistics.fmean(b)
            da = [value - ma for value in a]
            db = [value - mb for value in b]
            denominator = math.sqrt(
                sum(value * value for value in da)
                * sum(value * value for value in db)
            )
            if denominator:
                correlations.append(
                    sum(x * y for x, y in zip(da, db)) / denominator
                )
    return statistics.fmean(correlations) if correlations else math.nan


def metrics(bundle: Path) -> dict:
    summary = json.loads(
        (bundle / "ambient_iot" / "summary.json").read_text(encoding="utf-8")
    )
    offsets = event_offsets(bundle)
    transmitted = int(summary["transmitted"])
    collisions = int(summary["radio_collision_loss"])
    return {
        "active_fraction": active_fraction(bundle),
        "realized_power_correlation": pairwise_power_correlation(bundle),
        "decoded": int(summary["decoded"]),
        "decode_rate_per_s": len(offsets) / (DURATION_SECONDS - WARMUP_SECONDS),
        "fano_1s": fano_one_second(offsets),
        "gap_cv": gap_cv(offsets),
        "collision_rate": collisions / transmitted if transmitted else 0.0,
        "generated": int(summary["generated"]),
        "transmitted": transmitted,
        "collisions": collisions,
        "suppressed": int(summary["energy_or_protocol_suppressed"]),
    }


def finite_mean(values: list[float]) -> float:
    finite = [value for value in values if math.isfinite(float(value))]
    return statistics.fmean(finite) if finite else math.nan


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze Experiment 1 confirmation bundles without modifying them."
    )
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.results_root.expanduser().resolve()
    output = args.output or (root / "analysis-summary.json")
    records = []
    missing = []

    for condition in CONDITIONS:
        for seed in CONFIRMATION_SEEDS:
            bundle = root / f"{condition}-seed{seed}"
            if not (bundle / "ambient_iot" / "summary.json").is_file():
                missing.append(str(bundle))
                continue
            records.append({"condition": condition, "seed": seed, **metrics(bundle)})

    fields = (
        "active_fraction",
        "realized_power_correlation",
        "decode_rate_per_s",
        "fano_1s",
        "gap_cv",
        "collision_rate",
        "generated",
        "transmitted",
        "collisions",
        "suppressed",
    )
    condition_means = {}
    for condition in CONDITIONS:
        rows = [row for row in records if row["condition"] == condition]
        condition_means[condition] = {
            "n_runs": len(rows),
            "silent_runs": sum(row["decoded"] == 0 for row in rows),
            **{
                field: finite_mean([float(row[field]) for row in rows])
                for field in fields
            },
        }

    result = {
        "experiment": 1,
        "name": "Energy_Correlation_and_Burst_Formation",
        "analysis_window_seconds": [WARMUP_SECONDS, DURATION_SECONDS],
        "fano_window_seconds": 1.0,
        "runs_found": len(records),
        "runs_expected": len(CONDITIONS) * len(CONFIRMATION_SEEDS),
        "missing": missing,
        "condition_means": condition_means,
        "run_metrics": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "run_metrics"},
            indent=2,
            sort_keys=True,
        )
    )
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
