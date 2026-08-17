"""CLI registration and dispatch for SynthRAN experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from synthran.dependencies import load_lock
from synthran.experiment import ExperimentError, build_scenario
from synthran.experiment_runtime import (
    DEFAULT_COLLECTION_SECONDS,
    DEFAULT_MINIMUM_PER_SENSOR,
    execute_experiment,
)
from synthran.fiveg_ansible import load_inventory
from synthran.privacy import repository_root


def add_experiment_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the public ``synthran experiment`` command group."""

    experiment = subcommands.add_parser(
        "experiment",
        help="plan, run, or verify the deterministic IoT-to-5G experiment",
    )
    commands = experiment.add_subparsers(dest="experiment_command", required=True)

    plan = commands.add_parser(
        "plan",
        help="validate a path-proven network and print the experiment scenario",
    )
    plan.add_argument("--network-run-id", required=True)
    plan.add_argument("--run-id", required=True)
    plan.add_argument(
        "--network-run-root",
        type=Path,
        default=Path(".synthran/runs"),
        help=argparse.SUPPRESS,
    )

    run = commands.add_parser(
        "run",
        help="run the ten-sensor experiment against a path-proven network",
    )
    run.add_argument("--inventory", type=Path, required=True)
    run.add_argument("--network-run-id", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--lock", type=Path, default=Path("dependencies.lock.yml"))
    run.add_argument("--deps-root", type=Path, default=Path(".deps"))
    run.add_argument(
        "--network-run-root",
        type=Path,
        default=Path(".synthran/runs"),
        help=argparse.SUPPRESS,
    )
    run.add_argument(
        "--run-root",
        type=Path,
        default=Path(".synthran/experiments"),
        help=argparse.SUPPRESS,
    )
    run.add_argument(
        "--collection-seconds",
        type=int,
        default=DEFAULT_COLLECTION_SECONDS,
    )
    run.add_argument(
        "--minimum-per-sensor",
        type=int,
        default=DEFAULT_MINIMUM_PER_SENSOR,
    )

    verify = commands.add_parser(
        "verify",
        help="read persisted experiment acceptance evidence without changing live state",
    )
    verify.add_argument("--run-id", required=True)
    verify.add_argument(
        "--run-root",
        type=Path,
        default=Path(".synthran/experiments"),
        help=argparse.SUPPRESS,
    )


def _network_paths(root: Path, run_id: str) -> tuple[Path, Path]:
    directory = root.resolve() / run_id
    return directory / "manifest.json", directory / "network-evidence.json"


def _plan(args: argparse.Namespace) -> int:
    manifest, evidence = _network_paths(args.network_run_root, args.network_run_id)
    scenario = build_scenario(
        run_id=args.run_id,
        network_manifest=manifest,
        network_evidence=evidence,
    )
    print(json.dumps(scenario.to_dict(), indent=2, sort_keys=True))
    print(
        "\nPDU note: the displayed address is accepted network evidence;\n"
        "experiment execution rediscovers the live address after the srsUE rollout."
    )
    print("\nExecution action: none")
    print("Reservation action: none")
    print("Network deployment action: none")
    return 0


def _run(args: argparse.Namespace) -> int:
    manifest, evidence = _network_paths(args.network_run_root, args.network_run_id)
    result = execute_experiment(
        inventory=load_inventory(args.inventory),
        lock=load_lock(args.lock),
        dependency_root=args.deps_root,
        network_manifest=manifest,
        network_evidence=evidence,
        run_id=args.run_id,
        repository_root=repository_root(),
        run_root=args.run_root,
        collection_seconds=args.collection_seconds,
        minimum_per_sensor=args.minimum_per_sensor,
        progress=sys.stdout,
    )
    print(f"Run directory: {result.run_directory}")
    if result.evidence_path.is_file():
        print(f"Sanitized evidence: {result.evidence_path}")
    return 0 if result.ready else 2


def _verify(args: argparse.Namespace) -> int:
    run_directory = args.run_root.resolve() / args.run_id
    evidence_path = run_directory / "experiment-evidence.json"
    manifest_path = run_directory / "manifest.json"
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExperimentError("experiment manifest/evidence is missing") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExperimentError("experiment manifest/evidence must be readable JSON") from exc

    if not isinstance(evidence, dict) or evidence.get("schema") != "synthran/iot-evidence/v1alpha1":
        raise ExperimentError("experiment evidence schema is unsupported")
    if not isinstance(manifest, dict) or manifest.get("run_id") != args.run_id:
        raise ExperimentError("experiment manifest does not match the requested run")

    print(f"SynthRAN experiment verification ({args.run_id})")
    checks = evidence.get("checks")
    if not isinstance(checks, list):
        raise ExperimentError("experiment evidence checks are malformed")
    for check in checks:
        if not isinstance(check, dict):
            raise ExperimentError("experiment evidence contains a malformed check")
        state = "PASS" if check.get("passed") is True else "FAIL"
        print(f"[{state}] {check.get('name')}: {check.get('detail')}")
    ready = (
        evidence.get("ready") is True
        and manifest.get("status") == "iot-to-5g-path-proven"
    )
    print(f"Result: {'IOT-TO-5G PATH PROVEN' if ready else 'NOT PROVEN'}")
    return 0 if ready else 2


def dispatch_experiment(args: argparse.Namespace) -> int:
    """Dispatch a parsed ``synthran experiment`` command."""

    if args.experiment_command == "plan":
        return _plan(args)
    if args.experiment_command == "run":
        return _run(args)
    if args.experiment_command == "verify":
        return _verify(args)
    raise AssertionError("unreachable experiment command")
