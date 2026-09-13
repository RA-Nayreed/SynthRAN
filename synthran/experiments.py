"""Scientific experiment control plane for SynthRAN.

``experiment.sh`` is the only user-facing experiment launcher. This module owns
experiment manifests, scientific scenario loading, resource-aware parallelism,
and the handoff to runtime implementations. Individual studies live under
``Experiments/``.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Iterable, TypeVar

import yaml

from synthran.scenario import load_scenario as load_testbed

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = {
    "ex1": ROOT / "Experiments/Ex1_Energy_Correlation_and_Burst_Formation/experiment.yml",
}
REQUIRED_SECTIONS = ("model", "mqtt", "devices")
OPTIONAL_SECTIONS = ("measurement",)
SCIENTIFIC_SECTIONS = REQUIRED_SECTIONS + OPTIONAL_SECTIONS

T = TypeVar("T")
R = TypeVar("R")


def automatic_worker_count() -> int:
    """Return maximum CPU parallelism visible to this process."""

    try:
        available = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        available = os.cpu_count() or 1

    try:
        quota_text, period_text = Path("/sys/fs/cgroup/cpu.max").read_text(
            encoding="utf-8"
        ).split()
        if quota_text != "max":
            quota = int(quota_text)
            period = int(period_text)
            if quota > 0 and period > 0:
                available = min(available, max(1, math.ceil(quota / period)))
    except (FileNotFoundError, PermissionError, ValueError):
        pass
    return max(1, available)


def worker_environment() -> dict[str, str]:
    """Prevent nested BLAS/OpenMP pools from oversubscribing worker processes."""

    environment = dict(os.environ)
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        environment[name] = "1"
    return environment


def parallel_map(function: Callable[[T], R], items: Iterable[T]) -> list[R]:
    """Use maximum safe parallelism for independent CPU-bound run units.

    The result order remains deterministic even if workers finish out of order.
    Phase implementations decide which units are scientifically independent;
    dependency barriers are never crossed merely to increase utilization.
    """

    units = list(items)
    if not units:
        return []
    workers = min(automatic_worker_count(), len(units))
    if workers == 1:
        return [function(item) for item in units]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(function, units))


def scientific_settings(scenario: dict) -> dict:
    """Return the complete configured scientific contract without defaults."""

    return {key: scenario[key] for key in SCIENTIFIC_SECTIONS if key in scenario}


def _apply_experiment_settings(data: dict, settings: dict) -> None:
    if not isinstance(settings, dict):
        raise ValueError("experiment settings must be a mapping")
    for key in REQUIRED_SECTIONS:
        if key not in settings:
            raise ValueError(f"experiment settings require mapping: {key}")
        data[key] = settings[key]
    for key in OPTIONAL_SECTIONS:
        data.pop(key, None)
        if key in settings:
            data[key] = settings[key]


def load_scenario(path: str | Path) -> dict:
    """Load a scientific scenario, optionally wrapped by a testbed scenario."""

    source = Path(path).resolve()
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    data = load_testbed(source) if isinstance(raw, dict) and "deployment" in raw else raw
    if not isinstance(data, dict):
        raise ValueError("experiment scenario must be a mapping")

    experiment_config = data.get("experiment", {}).get("config")
    if experiment_config:
        source = Path(experiment_config)
        settings = yaml.safe_load(source.read_text(encoding="utf-8"))
        _apply_experiment_settings(data, settings)

    for section in REQUIRED_SECTIONS:
        if not isinstance(data.get(section), dict):
            raise ValueError(f"experiment requires mapping: {section}")
    if "measurement" in data and not isinstance(data["measurement"], dict):
        raise ValueError("experiment measurement must be a mapping")

    ues = data.get("deployment", {}).get("ues", data.get("gateways", []))
    if not data["devices"]:
        raise ValueError("devices must define at least one sensor")
    for name, device in data["devices"].items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name)
            or not isinstance(device, dict)
        ):
            raise ValueError("devices must map safe sensor names to configurations")
        gateway = device.get("gateway", name if name in ues else None)
        if gateway not in ues:
            raise ValueError(f"sensor {name!r} requires a gateway from deployment.ues")
        device["gateway"] = gateway

    data["_source_directory"] = str(source.parent)
    trace = data["model"].get("energy", {}).get("trace")
    if trace and not str(trace).startswith("builtin:"):
        data["model"]["energy"]["trace"] = str((source.parent / trace).resolve())
    for device in data["devices"].values():
        trace = device.get("energy", {}).get("trace")
        if trace and not str(trace).startswith("builtin:"):
            device["energy"]["trace"] = str((source.parent / trace).resolve())
    return data


def remap_gateways(scenario: dict, selected: list[str]) -> None:
    if not selected:
        raise ValueError("at least one gateway UE is required")
    original = list(scenario["deployment"]["ues"])
    replacement = {
        gateway: selected[index % len(selected)]
        for index, gateway in enumerate(original)
    }
    for name, device in scenario["devices"].items():
        gateway = device.get("gateway", name if name in original else None)
        target = gateway if gateway in selected else replacement.get(gateway)
        if target is None:
            raise ValueError(f"sensor {name!r} references unknown gateway {gateway!r}")
        device["gateway"] = target
    scenario["deployment"]["ues"] = list(selected)


def invoke(phase: str, config: str | Path, **options) -> None:
    """Invoke the runtime entrypoint selected by a deployment scenario."""

    selection = load_testbed(config).get("experiment")
    if not selection:
        if options.get("prepared_workload"):
            raise ValueError("--prepared-workload requires a configured experiment")
        return
    entrypoint = selection.get("entrypoint")
    if not entrypoint or not Path(entrypoint).is_file():
        raise ValueError("experiment.entrypoint must name an existing Python entrypoint")
    if phase == "configure" and not options.get("source_config"):
        source_config = selection.get("config")
        if not source_config:
            raise ValueError("experiment.configure requires experiment.config")
        options["source_config"] = source_config

    command = [sys.executable, entrypoint, phase, "--config", str(Path(config).resolve())]
    for name, value in options.items():
        if value:
            command.extend(["--" + name.replace("_", "-"), str(Path(value).resolve())])
    subprocess.run(command, check=True)


def _load_manifest(experiment: str) -> dict:
    try:
        path = EXPERIMENTS[experiment]
    except KeyError as exc:
        raise ValueError(f"unsupported experiment: {experiment}") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"experiment manifest is not a mapping: {path}")
    if data.get("id") != experiment:
        raise ValueError(f"manifest id mismatch for {experiment}")
    if not isinstance(data.get("resource"), dict):
        raise ValueError("manifest resource section must be a mapping")
    phases = data.get("phases")
    if not isinstance(phases, list) or not phases:
        raise ValueError("manifest phases must be a non-empty list")
    phase_ids = [phase.get("id") for phase in phases if isinstance(phase, dict)]
    if len(phase_ids) != len(phases) or any(not value for value in phase_ids):
        raise ValueError("every experiment phase requires an id")
    if len(set(phase_ids)) != len(phase_ids):
        raise ValueError("experiment phase ids must be unique")
    return data


def _selected_phases(manifest: dict, requested: str) -> list[dict]:
    if requested == "all":
        return manifest["phases"]
    for phase in manifest["phases"]:
        if phase["id"] == requested:
            return [phase]
    valid = ", ".join(phase["id"] for phase in manifest["phases"]) + ", all"
    raise ValueError(f"unknown phase {requested!r}; expected one of: {valid}")


def _section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def plan(experiment: str, phase: str, *, dry_run: bool, verbose: bool) -> None:
    manifest = _load_manifest(experiment)
    selected = _selected_phases(manifest, phase)
    resource = manifest["resource"]
    archive = manifest.get("archive", {})

    _section(f"Planning {manifest['display_name']}")
    print(f"Experiment        {manifest['id']}")
    print(f"Design version    {manifest['design_version']}")
    print(f"Resource          {str(resource.get('type', '')).upper()}")
    print(
        "Testbed           "
        + ("required" if resource.get("testbed_required") else "not required")
    )
    print(f"Requested phase   {phase}")
    print(f"Parallel workers  {automatic_worker_count()} available automatically")

    _section("Execution order")
    for index, item in enumerate(selected, start=1):
        print(f"  {index}. {item['id']:<24} {item['name']}")

    _section("Execution policy")
    print("Independent runs  maximum safe parallelism")
    print("Phase barriers    preserved")
    print("Numeric threads   1 per worker")
    print("Result identity   deterministic regardless of completion order")

    if archive:
        _section("Result archival")
        print(f"Backend           {archive.get('backend', 'disabled')}")
        print(f"After success     {bool(archive.get('upload_after_success', False))}")
        if archive.get("backend") == "s3":
            print(f"Alias             {archive.get('alias')}")
            print(f"Bucket            {archive.get('bucket')}")
            print(f"Prefix            {archive.get('prefix')}")
            print(f"Replay evidence   {archive.get('replay', 'if_available')}")

    if verbose:
        _section("Manifest")
        print(yaml.safe_dump(manifest, sort_keys=False).rstrip())
    if dry_run:
        _section("Mode")
        print("dry-run")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", choices=("plan",))
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan(args.experiment, args.phase, dry_run=args.dry_run, verbose=args.verbose)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Experiment error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
