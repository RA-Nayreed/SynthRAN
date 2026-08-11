"""Command-line interface for repository bootstrap and privacy controls."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Sequence

from synthran.dependencies import DependencyError, load_lock, sync_dependencies
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synthran")
    subcommands = parser.add_subparsers(dest="command", required=True)

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
    return parser


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


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "deps" and args.deps_command == "sync":
            return _deps_sync(args)
        if args.command == "privacy" and args.privacy_command == "scan":
            return _privacy_scan(args)
        if args.command == "privacy" and args.privacy_command == "redact":
            redact_file(args.source, args.destination, dry_run=args.dry_run, output=sys.stdout)
            return 0
        if args.command == "hooks" and args.hooks_command == "install":
            return _hooks_install(args)
    except (DependencyError, PrivacyError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    raise AssertionError("unreachable command dispatch")


if __name__ == "__main__":
    raise SystemExit(main())
