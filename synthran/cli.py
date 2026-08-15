"""Command-line interface for SynthRAN repository and experiment controls."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Sequence

from synthran.dependencies import DependencyError, load_lock, sync_dependencies
from synthran.fiveg_ansible import (
    FiveGAnsibleError,
    build_network_plan,
    load_inventory,
    run_offline_doctor,
)
from synthran.live_preflight import (
    LivePreflightError,
    run_live_preflight,
    save_live_evidence,
)
from synthran.network_runtime import (
    NetworkRuntimeError,
    execute_network_deployment,
    load_deployment_manifest,
    save_network_evidence,
    verify_network_path,
)
from synthran.privacy import (
    PrivacyError,
    outgoing_commits,
    redact_file,
    report_findings,
    repository_root,
    scan_commits,
    scan_history,
    scan_worktree,
)
from synthran.resource_runtime import (
    DEFAULT_DURATION_MINUTES,
    ResourcePreparationError,
    build_resource_preparation_plan,
    execute_resource_preparation,
)
from synthran.slices_controller import (
    DEFAULT_CONTROLLER_TIMEOUT_SECONDS,
    SlicesControllerError,
    verify_slices_controller,
)


def _add_slices_context(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--slices-project",
        default=os.environ.get("SYNTHRAN_SLICES_PROJECT"),
        help="selected SLICES project (or SYNTHRAN_SLICES_PROJECT)",
    )
    parser.add_argument(
        "--slices-experiment",
        default=os.environ.get("SYNTHRAN_SLICES_EXPERIMENT"),
        help="existing SLICES experiment (or SYNTHRAN_SLICES_EXPERIMENT)",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synthran")
    subcommands = parser.add_subparsers(dest="command", required=True)
    slices = subcommands.add_parser(
        "slices", help="verify the SLICES CLI controller context"
    )
    slices_commands = slices.add_subparsers(dest="slices_command", required=True)
    slices_doctor = slices_commands.add_parser(
        "doctor", help="read-only SLICES login, project, and experiment checks"
    )
    slices_doctor.add_argument("--lock", type=Path, default=Path("dependencies.lock.yml"))
    slices_doctor.add_argument(
        "--timeout", type=int, default=DEFAULT_CONTROLLER_TIMEOUT_SECONDS
    )
    _add_slices_context(slices_doctor)


    deps = subcommands.add_parser("deps", help="manage immutable external dependencies")
    deps_commands = deps.add_subparsers(dest="deps_command", required=True)
    sync = deps_commands.add_parser("sync", help="synchronize detached pinned checkouts")
    sync.add_argument("--lock", type=Path, default=Path("dependencies.lock.yml"))
    sync.add_argument("--root", type=Path, default=Path(".deps"))
    sync.add_argument("--all", action="store_true", help="include transitive repositories")
    sync.add_argument("--dry-run", action="store_true")

    privacy = subcommands.add_parser("privacy", help="scan or redact sensitive context")
    privacy_commands = privacy.add_subparsers(dest="privacy_command", required=True)
    scan = privacy_commands.add_parser("scan", help="fail when sensitive context is detected")
    scan_mode = scan.add_mutually_exclusive_group()
    scan_mode.add_argument("--worktree", action="store_true", help="scan tracked and unignored files")
    scan_mode.add_argument("--history", action="store_true", help="scan every Git commit")
    scan_mode.add_argument(
        "--outgoing",
        action="store_true",
        help="scan pre-push updates read from standard input",
    )
    scan.add_argument("--remote", default="origin", help="remote name used with --outgoing")

    redact = privacy_commands.add_parser("redact", help="write a sanitized text derivative")
    redact.add_argument("source", type=Path)
    redact.add_argument("destination", type=Path)
    redact.add_argument("--dry-run", action="store_true")

    hooks = subcommands.add_parser("hooks", help="configure repository-local Git hooks")
    hooks_commands = hooks.add_subparsers(dest="hooks_command", required=True)
    install = hooks_commands.add_parser("install", help="activate the tracked .githooks directory")
    install.add_argument("--dry-run", action="store_true")

    doctor = subcommands.add_parser("doctor", help="validate deployment prerequisites")
    _add_slices_context(doctor)
    doctor.add_argument("--inventory", type=Path, required=True)
    doctor.add_argument("--lock", type=Path, default=Path("dependencies.lock.yml"))
    doctor.add_argument("--deps-root", type=Path, default=Path(".deps"))
    doctor.add_argument(
        "--offline",
        action="store_true",
        help="validate only inventory, lock, and pinned checkout state",
    )
    doctor.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_CONTROLLER_TIMEOUT_SECONDS,
        help="timeout in seconds for each read-only live probe",
    )
    doctor.add_argument(
        "--owner",
        default=os.environ.get("SYNTHRAN_OWNER"),
        help="expected current SLICES/POS owner",
    )
    doctor.add_argument(
        "--reservation-id",
        default=os.environ.get("SYNTHRAN_RESERVATION_ID"),
        help="expected active reservation identifier",
    )
    doctor.add_argument(
        "--allocation-id",
        default=os.environ.get("SYNTHRAN_ALLOCATION_ID"),
        help="expected current allocation identifier",
    )
    doctor.add_argument(
        "--evidence-out",
        type=Path,
        help="write sanitized live readiness evidence (required for live doctor)",
    )

    network = subcommands.add_parser("network", help="plan or deploy the 5G network")
    network_commands = network.add_subparsers(dest="network_command", required=True)
    prepare = network_commands.add_parser(
        "prepare",
        help="explicitly reserve, allocate, image, and prepare a SLICES node pair",
    )
    _add_slices_context(prepare)
    prepare.add_argument("--core-node", default="sopnode-f2")
    prepare.add_argument("--ran-node", default="sopnode-f3")
    prepare.add_argument(
        "--owner",
        default=os.environ.get("SYNTHRAN_OWNER"),
        help="expected SLICES/POS owner (or SYNTHRAN_OWNER)",
    )
    prepare.add_argument(
        "--reservation-id",
        default=os.environ.get("SYNTHRAN_RESERVATION_ID"),
        help="reuse an active reservation instead of creating one",
    )
    prepare.add_argument(
        "--duration-minutes",
        type=int,
        default=DEFAULT_DURATION_MINUTES,
    )
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--lock", type=Path, default=Path("dependencies.lock.yml"))
    prepare.add_argument("--deps-root", type=Path, default=Path(".deps"))
    prepare.add_argument("--dry-run", action="store_true")
    prepare.add_argument("--json", action="store_true", help="emit a redacted JSON plan")
    prepare.add_argument(
        "--run-root",
        type=Path,
        default=Path(".synthran/preparations"),
        help=argparse.SUPPRESS,
    )
    prepare.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="timeout in seconds for each preparation stage",
    )
    deploy = network_commands.add_parser(
        "deploy", help="plan the explicit 5G network deployment"
    )
    _add_slices_context(deploy)
    deploy.add_argument("--inventory", type=Path, required=True)
    deploy.add_argument("--profile", default="default")
    deploy.add_argument("--lock", type=Path, default=Path("dependencies.lock.yml"))
    deploy.add_argument("--deps-root", type=Path, default=Path(".deps"))
    deploy.add_argument("--dry-run", action="store_true")
    deploy.add_argument("--json", action="store_true", help="emit a redacted JSON plan")
    deploy.add_argument(
        "--owner",
        default=os.environ.get("SYNTHRAN_OWNER"),
        help="expected current SLICES/POS owner",
    )
    deploy.add_argument(
        "--reservation-id",
        default=os.environ.get("SYNTHRAN_RESERVATION_ID"),
        help="expected active reservation identifier",
    )
    deploy.add_argument(
        "--allocation-id",
        default=os.environ.get("SYNTHRAN_ALLOCATION_ID"),
        help="expected current allocation identifier",
    )
    deploy.add_argument(
        "--preflight-evidence",
        type=Path,
        help="fresh READY evidence written by the live doctor",
    )
    deploy.add_argument("--run-id", help="unique lowercase run identifier")
    deploy.add_argument(
        "--run-root",
        type=Path,
        default=Path(".synthran/runs"),
        help=argparse.SUPPRESS,
    )
    deploy.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="timeout in seconds for each deployment stage",
    )

    verify = network_commands.add_parser(
        "verify", help="record gNB, srsUE, PDU tunnel, and UPF route evidence"
    )
    _add_slices_context(verify)
    verify.add_argument("--inventory", type=Path, required=True)
    verify.add_argument("--lock", type=Path, default=Path("dependencies.lock.yml"))
    verify.add_argument("--deps-root", type=Path, default=Path(".deps"))
    verify.add_argument("--run-id", required=True)
    verify.add_argument(
        "--run-root",
        type=Path,
        default=Path(".synthran/runs"),
        help=argparse.SUPPRESS,
    )
    verify.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="timeout in seconds for each read-only proof command",
    )
    return parser


def _require_slices_context(
    args: argparse.Namespace, operation: str
) -> tuple[str, str]:
    required = {
        "--slices-project": args.slices_project,
        "--slices-experiment": args.slices_experiment,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise SlicesControllerError(
            f"{operation} requires " + ", ".join(missing)
        )
    return args.slices_project, args.slices_experiment


def _slices_doctor(args: argparse.Namespace) -> int:
    project, experiment = _require_slices_context(args, "SLICES doctor")
    lock = load_lock(args.lock)
    report = verify_slices_controller(
        lock=lock,
        project=project,
        experiment=experiment,
        timeout_seconds=args.timeout,
    )
    print(report.render())
    return 0


def _deps_sync(args: argparse.Namespace) -> int:
    lock = load_lock(args.lock)
    sync_dependencies(
        lock,
        args.root,
        include_transitive=args.all,
        dry_run=args.dry_run,
        output=sys.stdout,
    )
    return 0


def _privacy_scan(args: argparse.Namespace) -> int:
    repo = repository_root()
    if args.outgoing:
        commits = outgoing_commits(repo, args.remote, sys.stdin)
        findings = scan_commits(repo, commits)
    elif args.history:
        findings = scan_history(repo)
    else:
        findings = scan_worktree(repo)
    return report_findings(findings, sys.stdout)


def _hooks_install(args: argparse.Namespace) -> int:
    repo = repository_root()
    hook = repo / ".githooks" / "pre-push"
    if not hook.is_file():
        raise PrivacyError("tracked pre-push hook is missing")
    if args.dry_run:
        print("[dry-run] make .githooks/pre-push executable when required")
        print("[dry-run] git config core.hooksPath .githooks")
        return 0
    if os.name != "nt":
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    try:
        subprocess.run(
            ["git", "config", "core.hooksPath", ".githooks"],
            cwd=repo,
            check=True,
            stdout=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise PrivacyError("unable to configure repository hooks") from exc
    print("repository hooks activated")
    return 0


def _doctor(args: argparse.Namespace) -> int:
    offline_report = run_offline_doctor(
        inventory_path=args.inventory,
        lock_path=args.lock,
        dependency_root=args.deps_root,
    )
    print(offline_report.render())
    if args.offline:
        return 0 if offline_report.ready else 2
    if not offline_report.ready:
        print("Live probes were not run because offline readiness failed.")
        return 2
    required = {
        "--slices-project": args.slices_project,
        "--slices-experiment": args.slices_experiment,
        "--owner": args.owner,
        "--reservation-id": args.reservation_id,
        "--allocation-id": args.allocation_id,
        "--evidence-out": args.evidence_out,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise LivePreflightError(
            "live doctor requires " + ", ".join(missing)
        )
    inventory = load_inventory(args.inventory)
    lock = load_lock(args.lock)
    live_report = run_live_preflight(
        inventory=inventory,
        lock=lock,
        owner=args.owner,
        reservation_id=args.reservation_id,
        allocation_id=args.allocation_id,
        slices_project=args.slices_project,
        slices_experiment=args.slices_experiment,
        timeout_seconds=args.timeout,
    )
    print()
    print(live_report.render())
    save_live_evidence(live_report, args.evidence_out)
    print(f"Sanitized evidence: {args.evidence_out.name}")
    return 0 if live_report.ready else 2


def _network_prepare(args: argparse.Namespace) -> int:
    lock = load_lock(args.lock)
    plan = build_resource_preparation_plan(
        lock=lock,
        core_node=args.core_node,
        ran_node=args.ran_node,
        duration_minutes=args.duration_minutes,
        run_id=args.run_id,
        reservation_id=args.reservation_id,
    )
    if args.dry_run:
        print(plan.render(as_json=args.json))
        return 0
    if args.json:
        raise ResourcePreparationError("--json is supported only with --dry-run")
    project, experiment = _require_slices_context(args, "live preparation")
    if args.owner is None:
        raise ResourcePreparationError(
            "live preparation requires --owner or SYNTHRAN_OWNER"
        )
    result = execute_resource_preparation(
        plan=plan,
        lock=lock,
        dependency_root=args.deps_root,
        owner=args.owner,
        slices_project=project,
        slices_experiment=experiment,
        reservation_id=args.reservation_id,
        run_root=args.run_root,
        repository_root=repository_root(),
        timeout_seconds=args.timeout,
    )
    print(f"SLICES resources prepared for run {result.run_id}.")
    print("Open5GS and srsRAN were not deployed.")
    print(f"Generated inventory: {result.inventory_path}")
    print(f"Private authority: {result.authority_path}")
    print(f"Sanitized manifest: {result.manifest_path}")
    print(f"Sanitized log: {result.log_path}")
    return 0


def _network_deploy(args: argparse.Namespace) -> int:
    if not args.dry_run:
        if args.json:
            raise FiveGAnsibleError("--json is supported only with --dry-run")
        required = {
            "--slices-project": args.slices_project,
            "--slices-experiment": args.slices_experiment,
            "--owner": args.owner,
            "--reservation-id": args.reservation_id,
            "--allocation-id": args.allocation_id,
            "--preflight-evidence": args.preflight_evidence,
            "--run-id": args.run_id,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise NetworkRuntimeError(
                "live deployment requires " + ", ".join(missing)
            )

    report = run_offline_doctor(
        inventory_path=args.inventory,
        lock_path=args.lock,
        dependency_root=args.deps_root,
    )
    if not report.ready:
        print(report.render(), file=sys.stderr)
        return 2
    lock = load_lock(args.lock)
    inventory = load_inventory(args.inventory)
    plan = build_network_plan(lock=lock, inventory=inventory, profile=args.profile)
    if not args.json:
        print(report.render())
        print()
    if args.dry_run:
        print(plan.render(as_json=args.json))
        return 0
    result = execute_network_deployment(
        plan=plan,
        lock=lock,
        dependency_root=args.deps_root,
        live_evidence_path=args.preflight_evidence,
        owner=args.owner,
        reservation_id=args.reservation_id,
        allocation_id=args.allocation_id,
        slices_project=args.slices_project,
        slices_experiment=args.slices_experiment,
        run_id=args.run_id,
        run_root=args.run_root,
        repository_root=repository_root(),
        timeout_seconds=args.timeout,
    )
    print(f"Deployment completed for run {result.run_id}; path proof is still required.")
    print(f"Sanitized manifest: {result.manifest_path}")
    print(f"Sanitized log: {result.log_path}")
    return 0


def _network_verify(args: argparse.Namespace) -> int:
    report = run_offline_doctor(
        inventory_path=args.inventory,
        lock_path=args.lock,
        dependency_root=args.deps_root,
    )
    if not report.ready:
        print(report.render(), file=sys.stderr)
        return 2
    lock = load_lock(args.lock)
    project, experiment = _require_slices_context(args, "network verification")
    active_controller = verify_slices_controller(
        lock=lock,
        project=project,
        experiment=experiment,
        timeout_seconds=args.timeout,
    )
    inventory = load_inventory(args.inventory)
    run_directory = args.run_root.resolve() / args.run_id
    manifest_path = run_directory / "manifest.json"
    manifest = load_deployment_manifest(
        path=manifest_path,
        run_id=args.run_id,
        inventory=inventory,
        lock=lock,
        slices_project=project,
        slices_experiment=experiment,
    )
    if manifest.get("slices_controller") != active_controller.to_dict():
        raise NetworkRuntimeError(
            "deployment manifest controller versions do not match the active shell"
        )
    verification = verify_network_path(
        inventory=inventory,
        lock=lock,
        run_id=args.run_id,
        timeout_seconds=args.timeout,
    )
    evidence_path = run_directory / "network-evidence.json"
    save_network_evidence(verification, evidence_path, manifest_path)
    print(verification.render())
    print(f"Sanitized evidence: {evidence_path}")
    return 0 if verification.ready else 2


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "slices" and args.slices_command == "doctor":
            return _slices_doctor(args)
        if args.command == "deps" and args.deps_command == "sync":
            return _deps_sync(args)
        if args.command == "privacy" and args.privacy_command == "scan":
            return _privacy_scan(args)
        if args.command == "privacy" and args.privacy_command == "redact":
            redact_file(args.source, args.destination, dry_run=args.dry_run, output=sys.stdout)
            return 0
        if args.command == "hooks" and args.hooks_command == "install":
            return _hooks_install(args)
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "network" and args.network_command == "prepare":
            return _network_prepare(args)
        if args.command == "network" and args.network_command == "deploy":
            return _network_deploy(args)
        if args.command == "network" and args.network_command == "verify":
            return _network_verify(args)
    except (
        DependencyError,
        FiveGAnsibleError,
        LivePreflightError,
        NetworkRuntimeError,
        PrivacyError,
        ResourcePreparationError,
        SlicesControllerError,
        OSError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    raise AssertionError("unreachable command dispatch")


if __name__ == "__main__":
    raise SystemExit(main())
