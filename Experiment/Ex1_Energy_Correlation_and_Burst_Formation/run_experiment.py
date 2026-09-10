#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_ROOT = ROOT / "results" / "exp1-energy-correlation"

DURATION_SECONDS = 60
SENSING_INTERVAL_MS = 1000
ENERGY_CV = 1.0
ENERGY_SAMPLE_INTERVAL_S = 0.1
ENERGY_CORRELATION_TIME_S = 5.0

POWER_GRID_W = (0.00025, 0.0005, 0.001, 0.002, 0.004)
POPULATION_GRID = (8, 16, 32, 64, 128)
PILOT_SEEDS = tuple(range(1, 6))

LOW_POWER_W = 0.0005
KNEE_POWER_W = 0.001
HIGH_POWER_W = 0.002
N_STAR = 32
CONFIRMATION_SEEDS = tuple(range(1001, 1031))

CONDITIONS = {
    "always-powered": {
        "mode": "always_powered",
        "correlation": "independent",
        "mean_power_w": KNEE_POWER_W,
    },
    "low-independent": {
        "mode": "environmental",
        "correlation": "independent",
        "mean_power_w": LOW_POWER_W,
    },
    "low-common": {
        "mode": "environmental",
        "correlation": "common",
        "mean_power_w": LOW_POWER_W,
    },
    "knee-independent": {
        "mode": "environmental",
        "correlation": "independent",
        "mean_power_w": KNEE_POWER_W,
    },
    "knee-common": {
        "mode": "environmental",
        "correlation": "common",
        "mean_power_w": KNEE_POWER_W,
    },
    "high-independent": {
        "mode": "environmental",
        "correlation": "independent",
        "mean_power_w": HIGH_POWER_W,
    },
    "high-common": {
        "mode": "environmental",
        "correlation": "common",
        "mean_power_w": HIGH_POWER_W,
    },
}


def scenario(sensor_count: int, seed: int, *, mode: str, correlation: str, mean_power_w: float) -> dict:
    devices = {
        f"sensor{index:02d}": {
            "gateway": "uesim01",
            "sensing_interval_ms": SENSING_INTERVAL_MS,
            "subcarrier_shift": 0,
        }
        for index in range(1, sensor_count + 1)
    }
    return {
        "deployment": {
            "core": "open5gs",
            "ran": "srsran",
            "platform": "rfsim",
            "profile": "default",
            "nodes": {
                "core": "sopnode-f2",
                "ran": "sopnode-f3",
                "broker": "sopnode-f2",
            },
            "ues": ["uesim01"],
            "reservation": {
                "enabled": False,
                "duration_minutes": 120,
                "image": "ubuntu-jammy",
            },
        },
        "model": {
            "engine": "ambient_iot",
            "seed": seed,
            "duration_seconds": DURATION_SECONDS,
            "energy": {
                "mode": mode,
                "source": "lognormal",
                "mean_power_w": mean_power_w,
                "coefficient_of_variation": ENERGY_CV,
                "sample_interval_s": ENERGY_SAMPLE_INTERVAL_S,
                "correlation_time_s": ENERGY_CORRELATION_TIME_S,
                "correlation": correlation,
                "interpolation": "hold",
            },
            "capacitor": {
                "capacitance_f": 0.0003,
                "series_resistance_ohm": 5000,
                "leakage_resistance_ohm": 100000,
                "initial_voltage_v": 0,
                "maximum_voltage_v": 2,
                "timestep_seconds": 0.001,
                "log_interval_seconds": 0.01,
            },
            "controller": {
                "low_voltage_v": 1.3,
                "high_voltage_v": 1.7,
                "max_startup_time_ms": 2000,
                "currents_a": {
                    "listening": 0.00014,
                    "sensing": 0.000512,
                    "processing": 0.00128,
                    "transmitting": 0.005,
                },
                "durations_ms": {
                    "sensing": 2,
                    "processing": 5,
                    "transmitting": 5,
                },
            },
            "topology": {
                "frequency_hz": 924000000,
                "pathloss": "macro",
                "nodes": {
                    "placement": {
                        "type": "random_annulus",
                        "min_radius_m": 10,
                        "max_radius_m": 40,
                    }
                },
                "base_station": {
                    "x": 0,
                    "y": 0,
                    "height_m": 25,
                    "sectors": [
                        {"azimuth_deg": 0, "beamwidth_deg": 65, "power_dbm": 46},
                        {"azimuth_deg": 120, "beamwidth_deg": 65, "power_dbm": 46},
                        {"azimuth_deg": 240, "beamwidth_deg": 65, "power_dbm": 46},
                    ],
                },
            },
            "propagation": {"model": "macro", "los": True},
            "protocol": {
                "type": "broadcast_sic",
                "slots": 4,
                "tx_duration_ms": 5,
                "rx_duration_ms": 10,
                "pre_registered": True,
            },
            "receiver": {
                "sic": True,
                "required_sinr_db": 3,
                "cancellation_factor": 0.9,
                "bandwidth_hz": 100000000,
                "noise_figure_db": 6,
            },
        },
        "mqtt": {
            "port": 1883,
            "qos": 1,
            "topic_prefix": "synthran",
            "payload_bytes": 256,
            "start_delay_seconds": 30,
        },
        "devices": devices,
    }


def valid_bundle(path: Path) -> bool:
    if not (path / "source-manifest.json").is_file():
        return False
    try:
        from Experiment.workload.bundle import validate_bundle
        validate_bundle(path)
    except Exception:
        return False
    return True


def run_one(results_root: Path, name: str, value: dict, resume: bool) -> None:
    output = results_root / name
    if output.exists() and any(output.iterdir()):
        if resume and valid_bundle(output):
            print(f"SKIP valid existing bundle: {output}")
            return
        raise SystemExit(f"Refusing to overwrite existing run: {output}")

    scenario_dir = results_root / "_scenarios"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    scenario_path = scenario_dir / f"{name}.yml"
    scenario_path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "Experiment.cli",
        "model",
        "run",
        "--config",
        str(scenario_path),
        "--output",
        str(output),
    ]
    print("$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def run_power_calibration(root: Path, resume: bool) -> None:
    for power_w in POWER_GRID_W:
        power_uw = int(round(power_w * 1e6))
        for seed in PILOT_SEEDS:
            run_one(
                root,
                f"calibration-power-{power_uw}uw-seed{seed}",
                scenario(
                    8,
                    seed,
                    mode="environmental",
                    correlation="independent",
                    mean_power_w=power_w,
                ),
                resume,
            )


def run_population_calibration(root: Path, resume: bool) -> None:
    for count in POPULATION_GRID:
        for seed in PILOT_SEEDS:
            run_one(
                root,
                f"calibration-population-n{count}-seed{seed}",
                scenario(
                    count,
                    seed,
                    mode="environmental",
                    correlation="independent",
                    mean_power_w=KNEE_POWER_W,
                ),
                resume,
            )


def run_confirmation(root: Path, resume: bool, conditions: list[str], seeds: list[int]) -> None:
    total = len(conditions) * len(seeds)
    completed = 0
    for condition in conditions:
        spec = CONDITIONS[condition]
        for seed in seeds:
            run_one(
                root,
                f"{condition}-seed{seed}",
                scenario(
                    N_STAR,
                    seed,
                    mode=str(spec["mode"]),
                    correlation=str(spec["correlation"]),
                    mean_power_w=float(spec["mean_power_w"]),
                ),
                resume,
            )
            completed += 1
            print(f"[{completed}/{total}] {condition}-seed{seed}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reproduce SynthRAN Experiment 1: energy correlation and burst formation."
    )
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument(
        "--phase",
        choices=("power-calibration", "population-calibration", "confirmation", "all"),
        default="confirmation",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Validate and skip existing immutable run directories instead of overwriting them.",
    )
    parser.add_argument("--condition", action="append", choices=tuple(CONDITIONS))
    parser.add_argument("--seed", action="append", type=int)
    args = parser.parse_args()

    root = args.results_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    if args.phase in {"power-calibration", "all"}:
        run_power_calibration(root, args.resume)
    if args.phase in {"population-calibration", "all"}:
        run_population_calibration(root, args.resume)
    if args.phase in {"confirmation", "all"}:
        conditions = args.condition or list(CONDITIONS)
        seeds = args.seed or list(CONFIRMATION_SEEDS)
        invalid = [seed for seed in seeds if seed not in CONFIRMATION_SEEDS]
        if invalid:
            raise SystemExit(f"confirmation seeds must be in 1001..1030; got {invalid}")
        run_confirmation(root, args.resume, conditions, seeds)

    print(f"Experiment 1 phase complete. Frozen confirmation population N*={N_STAR}.")


if __name__ == "__main__":
    main()
