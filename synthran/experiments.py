"""Scientific experiment control plane for SynthRAN.

``experiment.sh`` is the only user-facing experiment launcher. This module owns
experiment manifests, scientific scenario loading, resource-aware parallelism,
campaign identity, and the handoff to study/runtime implementations. Individual
studies live under ``Experiments/``.
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
import importlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Iterable, TypeVar

import yaml

from synthran.archive import archive_campaign_snapshot
from synthran.scenario import load_scenario as load_testbed

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = {
    "ex1": ROOT / "Experiments/Ex1_Energy_Correlation_and_Burst_Formation/experiment.yml",
}
RESULTS_ROOT = ROOT / "results/experiments"
ACTIVE_EXPERIMENT = ROOT / ".synthran/active-experiment.json"
REQUIRED_SECTIONS = ("model", "mqtt", "devices")
OPTIONAL_SECTIONS = ("measurement",)
SCIENTIFIC_SECTIONS = REQUIRED_SECTIONS + OPTIONAL_SECTIONS
_THREAD_ENV_NAMES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)
_EX1_PHASE_HANDLERS = {
    "power-calibration": (
        "Experiments.Ex1_Energy_Correlation_and_Burst_Formation.campaign",
        "power_calibration",
    ),
    "population-calibration": (
        "Experiments.Ex1_Energy_Correlation_and_Burst_Formation.population_calibration",
        "run",
    ),
    "freeze": (
        "Experiments.Ex1_Energy_Correlation_and_Burst_Formation.freeze",
        "run",
    ),
    "confirmation": (
        "Experiments.Ex1_Energy_Correlation_and_Burst_Formation.confirmation",
        "run",
    ),
    "analysis": (
        "Experiments.Ex1_Energy_Correlation_and_Burst_Formation.analysis_v2",
        "run",
    ),
}
_EX1_CAMPAIGN_ARCHIVE_FILES = {
    "freeze": (
        "campaign.json",
        "qualification/qualification.json",
        "calibration/power/summary.json",
        "calibration/power/selection.json",
        "calibration/population/summary.json",
        "calibration/population/selection.json",
        "frozen-design.json",
    ),
    "analysis": (
        "campaign.json",
        "frozen-design.json",
        "runs/index.json",
        "analysis/run-metrics.json",
        "analysis/summary.json",
    ),
}

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


def _configure_worker_threads() -> None:
    for name in _THREAD_ENV_NAMES:
        os.environ[name] = "1"


def _progress_detail(result: object) -> str:
    if not isinstance(result, dict):
        return "complete"
    parts: list[str] = []
    if result.get("status"):
        parts.append(str(result["status"]).lower())
    if result.get("resumed"):
        parts.append("reused")
    runtime = result.get("metrics", {}).get("runtime", {}) if isinstance(result.get("metrics"), dict) else {}
    wall = runtime.get("wall_seconds") if isinstance(runtime, dict) else None
    if wall is not None and not result.get("resumed"):
        parts.append(f"{float(wall):.1f}s")
    archive = result.get("archive")
    if isinstance(archive, dict):
        state = str(archive.get("archive_status", "")).upper()
        if state == "VERIFIED":
            parts.append("archived")
        elif state == "DISABLED":
            parts.append("archive disabled")
        elif state:
            parts.append(f"archive {state.lower()}")
    return " · ".join(parts) if parts else "complete"


def _progress_name(result: object, fallback: str) -> str:
    if isinstance(result, dict):
        value = result.get("name") or result.get("check")
        if value:
            return str(value)
    return fallback


def _print_parallel_header(total: int, workers: int) -> None:
    print(f"Run units         {total}", flush=True)
    print(f"Workers           {workers}", flush=True)
    print("Progress          live; completion lines include validation/archive state", flush=True)


def _print_parallel_completion(completed: int, total: int, result: object) -> None:
    width = len(str(total))
    name = _progress_name(result, f"unit-{completed}")
    detail = _progress_detail(result)
    print(f"  [{completed:>{width}}/{total}] {name}  ✓  {detail}", flush=True)


def parallel_map(function: Callable[[T], R], items: Iterable[T]) -> list[R]:
    """Run independent CPU-bound units at maximum safe parallelism with live progress.

    Results are returned in input order even though completion is reported as soon
    as each worker finishes. A heartbeat is printed while long-running units are
    still active so the terminal never looks stalled.
    """

    units = list(items)
    if not units:
        return []
    workers = min(automatic_worker_count(), len(units))
    _configure_worker_threads()
    _print_parallel_header(len(units), workers)

    if workers == 1:
        results: list[R] = []
        for index, item in enumerate(units, start=1):
            result = function(item)
            results.append(result)
            _print_parallel_completion(index, len(units), result)
        return results

    ordered: dict[int, R] = {}
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_configure_worker_threads,
    ) as executor:
        futures = {
            executor.submit(function, item): index
            for index, item in enumerate(units)
        }
        pending = set(futures)
        completed = 0
        while pending:
            done, pending = wait(
                pending,
                timeout=15.0,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                active = min(workers, len(pending))
                print(
                    f"  [{completed}/{len(units)}] working · "
                    f"{len(pending)} remaining · {active} workers active",
                    flush=True,
                )
                continue
            for future in sorted(done, key=lambda item: futures[item]):
                index = futures[future]
                result = future.result()
                ordered[index] = result
                completed += 1
                _print_parallel_completion(completed, len(units), result)
    return [ordered[index] for index in range(len(units))]


def scientific_settings(scenario: dict) -> dict:
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


def _source_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _new_campaign(experiment: str, manifest: dict) -> Path:
    campaign_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = RESULTS_ROOT / experiment / campaign_id
    root.mkdir(parents=True, exist_ok=False)
    campaign = {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "experiment": experiment,
        "design_version": manifest["design_version"],
        "status": "active",
        "source_revision": _source_revision(),
        "completed_phases": [],
    }
    _write_json(root / "campaign.json", campaign)
    ACTIVE_EXPERIMENT.parent.mkdir(parents=True, exist_ok=True)
    _write_json(
        ACTIVE_EXPERIMENT,
        {
            "schema_version": 1,
            "status": "active",
            "experiment": experiment,
            "campaign_id": campaign_id,
            "campaign_root": str(root),
            "campaign_file": str(root / "campaign.json"),
        },
    )
    return root


def _active_campaign(experiment: str) -> Path:
    if not ACTIVE_EXPERIMENT.is_file():
        raise ValueError("no active experiment campaign; run qualification first")
    endpoint = json.loads(ACTIVE_EXPERIMENT.read_text(encoding="utf-8"))
    if endpoint.get("status") != "active" or endpoint.get("experiment") != experiment:
        raise ValueError("active experiment state does not match the requested experiment")
    root = Path(endpoint.get("campaign_root", "")).resolve()
    campaign_file = root / "campaign.json"
    if not campaign_file.is_file():
        raise ValueError("active experiment campaign metadata is missing")
    campaign = json.loads(campaign_file.read_text(encoding="utf-8"))
    if (
        campaign.get("status") != "active"
        or campaign.get("campaign_id") != endpoint.get("campaign_id")
        or campaign.get("experiment") != experiment
    ):
        raise ValueError("active experiment endpoint does not match campaign metadata")
    return root


def _campaign(root: Path) -> dict:
    return json.loads((root / "campaign.json").read_text(encoding="utf-8"))


def _require_phase_dependencies(root: Path, item: dict) -> None:
    completed = set(_campaign(root).get("completed_phases", []))
    missing = [name for name in item.get("requires", []) if name not in completed]
    if missing:
        raise ValueError(
            f"phase {item['id']} requires completed phase(s): {', '.join(missing)}"
        )


def _mark_phase(root: Path, phase: str) -> None:
    path = root / "campaign.json"
    campaign = json.loads(path.read_text(encoding="utf-8"))
    completed = list(campaign.get("completed_phases", []))
    if phase not in completed:
        completed.append(phase)
    campaign["completed_phases"] = completed
    _write_json(path, campaign)


def _phase_handler(experiment: str, phase: str):
    if experiment != "ex1" or phase not in _EX1_PHASE_HANDLERS:
        raise ValueError(f"{experiment} phase {phase!r} is not implemented yet")
    module_name, function_name = _EX1_PHASE_HANDLERS[phase]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise ValueError(f"{experiment} phase {phase!r} is not implemented yet") from exc
        raise
    handler = getattr(module, function_name, None)
    if not callable(handler):
        raise ValueError(f"{experiment} phase {phase!r} has no callable implementation")
    return handler


def _archive_campaign_phase(root: Path, manifest: dict, phase: str) -> None:
    files = _EX1_CAMPAIGN_ARCHIVE_FILES.get(phase)
    settings = manifest.get("archive", {})
    if files is None or not bool(settings.get("enabled", False)):
        return
    archive_campaign_snapshot(
        root,
        settings=settings,
        phase=phase,
        selected_files=files,
    )
    print(f"Archive           VERIFIED · campaign {phase} snapshot")


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


def execute(experiment: str, phase: str, *, verbose: bool) -> None:
    manifest = _load_manifest(experiment)
    selected = _selected_phases(manifest, phase)
    root = (
        _new_campaign(experiment, manifest)
        if selected[0]["id"] == "qualification"
        else _active_campaign(experiment)
    )
    _section("Campaign")
    print(f"ID                {root.name}")
    print(f"Results           {root.relative_to(ROOT)}")
    print(f"Parallel workers  {automatic_worker_count()} available automatically")
    for item in selected:
        phase_id = item["id"]
        _require_phase_dependencies(root, item)
        _section(item["name"])
        if experiment == "ex1" and phase_id == "qualification":
            script = ROOT / "Experiments/Ex1_Energy_Correlation_and_Burst_Formation/qualification.py"
            subprocess.run(
                [sys.executable, str(script), "--output", str(root / "qualification")],
                cwd=ROOT,
                check=True,
            )
            result = json.loads(
                (root / "qualification/qualification.json").read_text(encoding="utf-8")
            )
            if result.get("status") != "passed":
                raise ValueError("Experiment 1 qualification did not pass")
            _mark_phase(root, phase_id)
            print("Qualification     PASSED")
            continue
        handler = _phase_handler(experiment, phase_id)
        result = handler(root)
        _archive_campaign_phase(root, manifest, phase_id)
        _mark_phase(root, phase_id)
        if isinstance(result, dict) and result.get("status"):
            print(f"Phase status      {str(result['status']).upper()}")
        else:
            print("Phase status      COMPLETE")
    if verbose:
        _section("Campaign state")
        print(json.dumps(_campaign(root), indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", choices=("plan", "run"))
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            plan(args.experiment, args.phase, dry_run=args.dry_run, verbose=args.verbose)
        else:
            execute(args.experiment, args.phase, verbose=args.verbose)
    except (OSError, ValueError, yaml.YAMLError, subprocess.CalledProcessError) as exc:
        print(f"Experiment error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
