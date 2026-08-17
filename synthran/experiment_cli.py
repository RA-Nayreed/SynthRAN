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
from synthran.research import (
    DEFAULT_MEASUREMENT_SECONDS,
    DEFAULT_PAYLOAD_BYTES,
    DEFAULT_SAMPLE_INTERVAL_SECONDS,
    DEFAULT_SENSOR_PERIOD_SECONDS,
    DEFAULT_WARMUP_SECONDS,
    LoadProfile,
    ResearchSpec,
    analyze_campaign,
    build_campaign_plan,
    load_campaign_plan,
    save_campaign_plan,
)
from synthran.research_runtime import execute_research_campaign, execute_research_run


def _comma_ints(value: str) -> tuple[int, ...]:
    try:
        parsed = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated integers") from exc
    if not parsed:
        raise argparse.ArgumentTypeError("expected at least one integer")
    return parsed


def _comma_floats(value: str) -> tuple[float, ...]:
    try:
        parsed = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated numbers") from exc
    if not parsed:
        raise argparse.ArgumentTypeError("expected at least one number")
    return parsed


def _comma_strings(value: str) -> tuple[str, ...]:
    parsed = tuple(item.strip() for item in value.split(",") if item.strip())
    if not parsed:
        raise argparse.ArgumentTypeError("expected at least one value")
    return parsed


def _add_research_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--network-run-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--sensor-period-seconds",
        type=int,
        default=DEFAULT_SENSOR_PERIOD_SECONDS,
    )
    parser.add_argument(
        "--warmup-seconds", type=int, default=DEFAULT_WARMUP_SECONDS
    )
    parser.add_argument(
        "--measurement-seconds", type=int, default=DEFAULT_MEASUREMENT_SECONDS
    )
    parser.add_argument(
        "--sample-interval-seconds",
        type=float,
        default=DEFAULT_SAMPLE_INTERVAL_SECONDS,
    )
    parser.add_argument("--payload-bytes", type=int, default=DEFAULT_PAYLOAD_BYTES)


def _add_research_live_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=Path("dependencies.lock.yml"))
    parser.add_argument("--deps-root", type=Path, default=Path(".deps"))
    parser.add_argument(
        "--network-run-root",
        type=Path,
        default=Path(".synthran/runs"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path(".synthran/experiments"),
        help=argparse.SUPPRESS,
    )


def add_experiment_parser(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the public ``synthran experiment`` command group."""

    experiment = subcommands.add_parser(
        "experiment",
        help="plan, run, verify, or analyze deterministic IoT-to-5G experiments",
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

    research_plan = commands.add_parser(
        "research-plan",
        help="render a baseline, congestion, or calibration research specification",
    )
    _add_research_common(research_plan)
    research_plan.add_argument(
        "--condition",
        choices=("baseline", "congestion", "calibration"),
        required=True,
    )
    research_plan.add_argument("--target-fraction", type=float, default=0.0)
    research_plan.add_argument("--reference-kbps", type=float)

    research_run = commands.add_parser(
        "research-run",
        help="execute a measured research condition on the accepted IoT-to-5G path",
    )
    _add_research_common(research_run)
    _add_research_live_common(research_run)
    research_run.add_argument(
        "--condition",
        choices=("baseline", "congestion", "calibration"),
        required=True,
    )
    research_run.add_argument("--target-fraction", type=float, default=0.0)
    research_run.add_argument("--reference-kbps", type=float)

    campaign_plan = commands.add_parser(
        "campaign-plan",
        help="build a deterministic blocked and randomized research campaign",
    )
    campaign_plan.add_argument("--campaign-id", required=True)
    campaign_plan.add_argument("--network-run-id", required=True)
    campaign_plan.add_argument("--seeds", type=_comma_ints, required=True)
    campaign_plan.add_argument(
        "--congestion-fractions", type=_comma_floats, required=True
    )
    campaign_plan.add_argument("--reference-kbps", type=float, required=True)
    campaign_plan.add_argument("--randomization-seed", type=int, required=True)
    campaign_plan.add_argument("--output", type=Path)

    campaign_run = commands.add_parser(
        "campaign-run",
        help="execute a saved research campaign sequentially and stop on invalid evidence",
    )
    campaign_run.add_argument("--campaign", type=Path, required=True)
    campaign_run.add_argument("--inventory", type=Path, required=True)
    campaign_run.add_argument("--lock", type=Path, default=Path("dependencies.lock.yml"))
    campaign_run.add_argument("--deps-root", type=Path, default=Path(".deps"))
    campaign_run.add_argument(
        "--network-run-root",
        type=Path,
        default=Path(".synthran/runs"),
        help=argparse.SUPPRESS,
    )
    campaign_run.add_argument(
        "--run-root",
        type=Path,
        default=Path(".synthran/experiments"),
        help=argparse.SUPPRESS,
    )
    campaign_run.add_argument(
        "--sensor-period-seconds",
        type=int,
        default=DEFAULT_SENSOR_PERIOD_SECONDS,
    )
    campaign_run.add_argument(
        "--warmup-seconds", type=int, default=DEFAULT_WARMUP_SECONDS
    )
    campaign_run.add_argument(
        "--measurement-seconds", type=int, default=DEFAULT_MEASUREMENT_SECONDS
    )
    campaign_run.add_argument(
        "--sample-interval-seconds",
        type=float,
        default=DEFAULT_SAMPLE_INTERVAL_SECONDS,
    )
    campaign_run.add_argument("--payload-bytes", type=int, default=DEFAULT_PAYLOAD_BYTES)

    campaign_analyze = commands.add_parser(
        "campaign-analyze",
        help="analyze persisted research runs without touching live infrastructure",
    )
    campaign_analyze.add_argument("--campaign-id", required=True)
    campaign_analyze.add_argument("--run-ids", type=_comma_strings, required=True)
    campaign_analyze.add_argument(
        "--run-root", type=Path, default=Path(".synthran/experiments")
    )
    campaign_analyze.add_argument("--output", type=Path, required=True)


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

    if (
        not isinstance(evidence, dict)
        or evidence.get("schema") != "synthran/iot-evidence/v1alpha1"
    ):
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


def _research_spec(args: argparse.Namespace) -> ResearchSpec:
    target_fraction = args.target_fraction
    if args.condition == "baseline":
        target_fraction = 0.0
    elif args.condition == "calibration":
        target_fraction = 1.0
    return ResearchSpec(
        campaign_id=args.campaign_id,
        run_id=args.run_id,
        network_run_id=args.network_run_id,
        condition=args.condition,
        cooja_seed=args.seed,
        sensor_period_seconds=args.sensor_period_seconds,
        warmup_seconds=args.warmup_seconds,
        measurement_seconds=args.measurement_seconds,
        sample_interval_seconds=args.sample_interval_seconds,
        load=LoadProfile(
            args.condition,
            target_fraction=target_fraction,
            reference_kbps=args.reference_kbps,
            payload_bytes=args.payload_bytes,
        ),
    )


def _research_plan(args: argparse.Namespace) -> int:
    print(json.dumps(_research_spec(args).to_dict(), indent=2, sort_keys=True))
    print("\nExecution action: none")
    print("Reservation action: none")
    print("Network deployment action: none")
    return 0


def _research_run(args: argparse.Namespace) -> int:
    spec = _research_spec(args)
    manifest, evidence = _network_paths(args.network_run_root, args.network_run_id)
    result = execute_research_run(
        spec=spec,
        inventory=load_inventory(args.inventory),
        lock=load_lock(args.lock),
        dependency_root=args.deps_root,
        network_manifest=manifest,
        network_evidence=evidence,
        repository_root=repository_root(),
        run_root=args.run_root,
        progress=sys.stdout,
    )
    print(f"Run directory: {result.experiment.run_directory}")
    print(f"Research summary: {result.summary_path}")
    print(f"Research result: {'VALID' if result.valid else 'INVALID'}")
    return 0 if result.valid else 2


def _campaign_plan(args: argparse.Namespace) -> int:
    plan = build_campaign_plan(
        campaign_id=args.campaign_id,
        network_run_id=args.network_run_id,
        seeds=args.seeds,
        congestion_fractions=args.congestion_fractions,
        reference_kbps=args.reference_kbps,
        randomization_seed=args.randomization_seed,
    )
    if args.output is not None:
        save_campaign_plan(plan, args.output)
        print(f"Campaign plan: {args.output}")
    else:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    return 0


def _campaign_run(args: argparse.Namespace) -> int:
    plan = load_campaign_plan(args.campaign)
    manifest, evidence = _network_paths(args.network_run_root, plan.network_run_id)
    result = execute_research_campaign(
        plan=plan,
        inventory=load_inventory(args.inventory),
        lock=load_lock(args.lock),
        dependency_root=args.deps_root,
        network_manifest=manifest,
        network_evidence=evidence,
        repository_root=repository_root(),
        run_root=args.run_root,
        warmup_seconds=args.warmup_seconds,
        measurement_seconds=args.measurement_seconds,
        sample_interval_seconds=args.sample_interval_seconds,
        payload_bytes=args.payload_bytes,
        sensor_period_seconds=args.sensor_period_seconds,
        progress=sys.stdout,
    )
    print(f"Campaign runs completed: {len(result.runs)}/{len(plan.runs)}")
    print(f"Campaign result: {'VALID' if result.valid else 'INCOMPLETE OR INVALID'}")
    return 0 if result.valid else 2


def _campaign_analyze(args: argparse.Namespace) -> int:
    summary = analyze_campaign(
        campaign_id=args.campaign_id,
        run_root=args.run_root.resolve(),
        run_ids=args.run_ids,
        destination=args.output,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Campaign summary: {args.output}")
    return 0


def dispatch_experiment(args: argparse.Namespace) -> int:
    """Dispatch a parsed ``synthran experiment`` command."""

    if args.experiment_command == "plan":
        return _plan(args)
    if args.experiment_command == "run":
        return _run(args)
    if args.experiment_command == "verify":
        return _verify(args)
    if args.experiment_command == "research-plan":
        return _research_plan(args)
    if args.experiment_command == "research-run":
        return _research_run(args)
    if args.experiment_command == "campaign-plan":
        return _campaign_plan(args)
    if args.experiment_command == "campaign-run":
        return _campaign_run(args)
    if args.experiment_command == "campaign-analyze":
        return _campaign_analyze(args)
    raise AssertionError("unreachable experiment command")
