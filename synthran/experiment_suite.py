"""Internal planning support for the standalone ``experiment.sh`` frontend.

This module is deliberately not a second public CLI. ``experiment.sh`` is the
user-facing control surface; this module owns structured manifest validation and
will later dispatch experiment phases.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = {
    "ex1": ROOT / "Experiment/Ex1_Energy_Correlation_and_Burst_Formation/experiment.yml",
}


def _section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


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
    resource = data.get("resource")
    if not isinstance(resource, dict):
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
    phases = manifest["phases"]
    if requested == "all":
        return phases
    for phase in phases:
        if phase["id"] == requested:
            return [phase]
    valid = ", ".join(phase["id"] for phase in phases) + ", all"
    raise ValueError(f"unknown phase {requested!r}; expected one of: {valid}")


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

    _section("Execution order")
    for index, item in enumerate(selected, start=1):
        print(f"  {index}. {item['id']:<24} {item['name']}")

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

    _section("Development status")
    print("This increment establishes the standalone experiment interface and")
    print("the frozen Experiment 1 lifecycle contract. Scientific phase execution")
    print("is intentionally added in subsequent commits, one phase at a time.")
    if dry_run:
        print("Mode              dry-run")


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
        print(f"Experiment plan error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
