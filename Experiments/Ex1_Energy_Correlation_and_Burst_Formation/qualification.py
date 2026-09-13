#!/usr/bin/env python3
"""Scientific qualification gate for Experiment 1 v2.

These checks are retained research evidence, not a disposable unit-test suite.
Calibration is not allowed to start unless every qualification contract passes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import simpy
import yaml

from synthran.ambient_iot import AmbientIoTRunner
from synthran.ambient_iot.config import TraceEnergySource, energy_sources
from synthran.experiments import parallel_map
from synthran.model.capacitor import Capacitor, CapacitorParams
from synthran.model.receiver import decode_receptions
from synthran.workload.bundle import validate_bundle
from synthran.workload.trace import generate

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "scenario-template.yml"


def _revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _result(name: str, criterion: str, observed: dict, passed: bool) -> dict:
    return {
        "check": name,
        "status": "passed" if passed else "failed",
        "criterion": criterion,
        "observed": observed,
    }


def _scenario(*, sensors: int = 1, duration_s: float = 3.5) -> dict:
    value = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    model = value["model"]
    model["seed"] = 4242
    model["duration_seconds"] = duration_s
    model["energy"] = {
        "mode": "always_powered",
        "source": "trace",
        "constant_power_w": 0.0,
        "correlation": "common",
        "interpolation": "hold",
        "repeat": False,
    }
    model["controller"]["max_startup_time_ms"] = 0
    value["devices"] = {
        f"sensor{index:02d}": {
            "gateway": "uesim01",
            "energy_mode": "always_powered",
            "sensing_interval_ms": 500,
            "sensing_phase_ms": 100,
            "x": 10 + index,
            "y": 0,
        }
        for index in range(1, sensors + 1)
    }
    return value


def _constant_power(directory: Path) -> dict:
    env = simpy.Environment()
    source = TraceEnergySource(
        env,
        {"constant_power_w": 0.00125, "repeat": False},
    )
    samples = {str(t): source.power_at(t) for t in (0, 0.1, 1.0, 99.0)}
    passed = all(math.isclose(value, 0.00125, rel_tol=0, abs_tol=1e-15) for value in samples.values())
    return _result(
        "constant-power",
        "A constant-power source returns the configured wattage at every sampled timestamp.",
        {"samples_w": samples},
        passed,
    )


def _zero_power(directory: Path) -> dict:
    env = simpy.Environment()
    source = TraceEnergySource(env, {"constant_power_w": 0.0, "repeat": False})
    samples = [source.power_at(t) for t in (0, 0.25, 10.0)]

    cap = Capacitor(
        env,
        0,
        CapacitorParams(dt=0.001, R_series=5000, R_leakage=math.inf, C=300e-6),
        keep_logs=False,
        initial_voltage=0,
        voltage_max=2,
    )
    cap.voltage_source = 0
    cap.advance(seconds=1.0)
    passed = all(value == 0 for value in samples) and cap.voltage == 0 and cap.energy == 0
    return _result(
        "zero-power",
        "Zero harvested power cannot create capacitor energy from a zero-energy initial state.",
        {"samples_w": samples, "voltage_v": cap.voltage, "stored_j": cap.energy},
        passed,
    )


def _irregular_trace(directory: Path) -> dict:
    trace = directory / "irregular.csv"
    trace.parent.mkdir(parents=True, exist_ok=True)
    with trace.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s", "power_w"])
        writer.writerows(
            [(0.0, 0.0001), (0.2, 0.0002), (1.3, 0.0004), (2.0, 0.0008)]
        )
    source = TraceEnergySource(
        simpy.Environment(),
        {"trace": str(trace), "interpolation": "hold", "repeat": False},
    )
    probes = {
        "0.10": source.power_at(0.10),
        "0.20": source.power_at(0.20),
        "1.29": source.power_at(1.29),
        "1.30": source.power_at(1.30),
        "2.50": source.power_at(2.50),
    }
    expected = {
        "0.10": 0.0001,
        "0.20": 0.0002,
        "1.29": 0.0002,
        "1.30": 0.0004,
        "2.50": 0.0008,
    }
    passed = all(math.isclose(probes[key], value, rel_tol=0, abs_tol=1e-15) for key, value in expected.items())
    return _result(
        "irregular-trace",
        "Hold interpolation changes power at the trace's actual irregular timestamps, not at an assumed fixed sample period.",
        {"probes_w": probes, "expected_w": expected},
        passed,
    )


def _capacitor_known_trajectory(directory: Path) -> dict:
    env = simpy.Environment()
    params = CapacitorParams(dt=0.001, R_series=5000, R_leakage=math.inf, C=300e-6)
    cap = Capacitor(env, 0, params, keep_logs=False, initial_voltage=0, voltage_max=2)
    cap.voltage_source = 1.0
    seconds = 0.5
    cap.advance(seconds=seconds)
    expected = 1.0 * (1 - math.exp(-seconds / (params.R_series * params.C)))
    error = abs(cap.voltage - expected)
    passed = error <= 1e-12
    return _result(
        "capacitor-known-trajectory",
        "With no leakage/load/clamping, capacitor voltage follows the closed-form series-RC charging solution.",
        {"expected_voltage_v": expected, "observed_voltage_v": cap.voltage, "absolute_error_v": error},
        passed,
    )


def _capacitor_accounting(directory: Path) -> dict:
    env = simpy.Environment()
    cap = Capacitor(
        env,
        0,
        CapacitorParams(dt=0.001, R_series=5000, R_leakage=100000, C=300e-6),
        keep_logs=False,
        initial_voltage=0.4,
        voltage_max=1.5,
    )
    cap.voltage_source = 2.0
    initial = cap.energy
    cap.advance(load_current=0.00012, seconds=2.0)
    account = dict(cap.energy_account)
    inputs = initial + account["source_j"]
    outputs = cap.energy + sum(
        account[key]
        for key in ("series_loss_j", "leakage_j", "load_j", "clamp_loss_j")
    )
    residual = inputs - outputs
    tolerance = max(1e-12, abs(inputs) * 1e-9)
    passed = abs(residual) <= tolerance and all(value >= 0 for value in account.values())
    return _result(
        "capacitor-accounting",
        "Initial plus source energy closes against stored energy, load, series, leakage and clamp losses.",
        {
            "initial_j": initial,
            "stored_j": cap.energy,
            **account,
            "closure_residual_j": residual,
            "tolerance_j": tolerance,
        },
        passed,
    )


def _energy_dependence(directory: Path) -> dict:
    devices = {f"sensor{i:02d}": {} for i in range(1, 4)}
    names = {index: name for index, name in enumerate(sorted(devices))}
    base = {
        "source": "lognormal",
        "mean_power_w": 0.001,
        "coefficient_of_variation": 1.0,
        "sample_interval_s": 0.1,
        "correlation_time_s": 0.5,
    }

    common = energy_sources(
        simpy.Environment(), {**base, "correlation": "common"}, devices, names, 10000, 77, None
    )
    independent = energy_sources(
        simpy.Environment(), {**base, "correlation": "independent"}, devices, names, 10000, 77, None
    )
    common_arrays = [common[index].values for index in sorted(common)]
    independent_arrays = [independent[index].values for index in sorted(independent)]
    common_identical = all(np.array_equal(common_arrays[0], values) for values in common_arrays[1:])
    independent_distinct = all(not np.array_equal(independent_arrays[0], values) for values in independent_arrays[1:])
    common_corr = float(np.corrcoef(common_arrays[0], common_arrays[1])[0, 1])
    independent_corr = float(np.corrcoef(independent_arrays[0], independent_arrays[1])[0, 1])
    return _result(
        "energy-dependence",
        "Common harvesting produces one shared sample path; independent harvesting produces distinct per-device sample paths for the same seed.",
        {
            "common_identical": common_identical,
            "independent_distinct": independent_distinct,
            "realized_common_pearson": common_corr,
            "realized_independent_pearson": independent_corr,
            "samples_per_sensor": len(common_arrays[0]),
        },
        common_identical and independent_distinct,
    )


def _sensing_periodicity(directory: Path) -> dict:
    scenario = _scenario(sensors=1, duration_s=3.5)
    result = AmbientIoTRunner(scenario).run()
    rows = result["controllers"][0].opportunities
    observed = [round(row["time_ms"], 9) for row in rows]
    expected = []
    value = 100.0
    while value < 3500.0:
        expected.append(value)
        value += 500.0
    indices = [row["opportunity_index"] for row in rows]
    passed = observed == expected and indices == list(range(len(expected)))
    return _result(
        "sensing-periodicity",
        "Sensing opportunities occur exactly at phase + k·interval with no retrospective catch-up.",
        {"expected_ms": expected, "observed_ms": observed, "indices": indices},
        passed,
    )


def _packet(rssi: float, start: float, end: float) -> dict:
    return {
        "rssi_dbm": rssi,
        "sensitivity_dbm": -100.0,
        "start_ms": start,
        "end_ms": end,
        "energy_complete": True,
    }


def _receiver_singleton(directory: Path) -> dict:
    decision = decode_receptions([_packet(-60, 0, 5)], 1e-12, 3, 0.9, True)[0]
    passed = decision["outcome"] == "decoded" and decision["sinr_db"] >= 3
    return _result(
        "receiver-singleton",
        "A sufficiently strong isolated packet is decoded and reports SINR above threshold.",
        decision,
        passed,
    )


def _receiver_collision(directory: Path) -> dict:
    overlapping = decode_receptions(
        [_packet(-60, 0, 5), _packet(-60, 0, 5)], 1e-12, 3, 0.9, False
    )
    adjacent = decode_receptions(
        [_packet(-60, 0, 5), _packet(-60, 5, 10)], 1e-12, 3, 0.9, False
    )
    passed = (
        [item["outcome"] for item in overlapping] == ["collision", "collision"]
        and [item["outcome"] for item in adjacent] == ["decoded", "decoded"]
    )
    return _result(
        "receiver-collision",
        "Equal-power overlapping airtime collides without SIC, while boundary-adjacent non-overlapping packets decode independently.",
        {"overlapping": overlapping, "adjacent": adjacent},
        passed,
    )


def _receiver_sic(directory: Path) -> dict:
    packets = [_packet(-50, 0, 5), _packet(-60, 0, 5)]
    disabled = decode_receptions(packets, 1e-12, 3, 1.0, False)
    enabled = decode_receptions(packets, 1e-12, 3, 1.0, True)
    passed = (
        disabled[0]["outcome"] == "capture"
        and disabled[1]["outcome"] == "collision"
        and enabled[0]["outcome"] == "capture"
        and enabled[1]["outcome"] == "sic_recovered"
        and enabled[1]["decode_stage"] == 1
    )
    return _result(
        "receiver-sic",
        "Perfect cancellation recovers the weaker overlapping packet after the stronger capture; disabling SIC does not.",
        {"sic_disabled": disabled, "sic_enabled": enabled},
        passed,
    )


def _event_lineage_bundle(directory: Path) -> dict:
    scenario = _scenario(sensors=1, duration_s=4.0)
    scenario_path = directory / "scenario.yml"
    bundle = directory / "bundle"
    directory.mkdir(parents=True, exist_ok=True)
    scenario_path.write_text(yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8")
    generate(scenario_path, bundle)
    manifest = validate_bundle(bundle)

    generated = []
    with (bundle / "ambient_iot/sample-events.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("kind") == "generated":
                generated.append(row)
    events = [json.loads(line) for line in (bundle / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]
    generated_ids = {row["event_id"] for row in generated}
    event_ids = [row["event_id"] for row in events]
    payload_ok = True
    chronology_ok = True
    for event in events:
        payload = json.loads(event["payload"])
        payload_ok &= (
            payload["event_id"] == event["event_id"]
            and payload["device"] == event["device"]
            and hashlib.sha256(event["payload"].encode()).hexdigest() == event["payload_sha256"]
        )
        chronology_ok &= (
            event["generated_time_s"] <= event["decode_time_s"] == event["time_offset_s"]
        )
    passed = (
        bool(events)
        and len(event_ids) == len(set(event_ids))
        and set(event_ids) <= generated_ids
        and payload_ok
        and chronology_ok
        and manifest["event_count"] == len(events)
        and manifest["transformation"]["generation_age_valid"] is True
    )
    return _result(
        "event-lineage-bundle",
        "Every canonical event is a unique generated sample forwarded only after decode, with matching serialized identity, checksum, chronology and immutable bundle manifest.",
        {
            "generated_samples": len(generated),
            "decoded_events": len(events),
            "unique_event_ids": len(set(event_ids)),
            "payload_identity_and_sha256": payload_ok,
            "chronology_valid": chronology_ok,
            "bundle_sha256": manifest["bundle_sha256"],
        },
        passed,
    )


CHECKS = {
    "constant-power": _constant_power,
    "zero-power": _zero_power,
    "irregular-trace": _irregular_trace,
    "capacitor-known-trajectory": _capacitor_known_trajectory,
    "capacitor-accounting": _capacitor_accounting,
    "energy-dependence": _energy_dependence,
    "sensing-periodicity": _sensing_periodicity,
    "receiver-singleton": _receiver_singleton,
    "receiver-collision": _receiver_collision,
    "receiver-sic": _receiver_sic,
    "event-lineage-bundle": _event_lineage_bundle,
}


def _execute(item: tuple[str, str]) -> dict:
    name, root_text = item
    root = Path(root_text)
    directory = root / name
    try:
        result = CHECKS[name](directory)
    except Exception as exc:  # retain failure evidence instead of losing the campaign
        result = {
            "check": name,
            "status": "failed",
            "criterion": "qualification check completed without exception",
            "observed": {"exception": type(exc).__name__, "message": str(exc)},
        }
    _json(directory / "result.json", result)
    return result


def qualify(output: Path) -> dict:
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"refusing to overwrite qualification evidence: {output}")
    output.mkdir(parents=True, exist_ok=True)
    items = [(name, str(output)) for name in CHECKS]
    results = parallel_map(_execute, items)
    failed = [result["check"] for result in results if result["status"] != "passed"]
    summary = {
        "schema_version": 1,
        "status": "passed" if not failed else "failed",
        "source_revision": _revision(),
        "parallel_checks": True,
        "checks_total": len(results),
        "checks_passed": len(results) - len(failed),
        "checks_failed": failed,
        "checks": {result["check"]: result["status"] for result in results},
    }
    _json(output / "qualification.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = qualify(args.output)
    print(json.dumps(summary, indent=2))
    if summary["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
