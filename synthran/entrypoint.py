"""Unified SynthRAN command-line entrypoint."""

from __future__ import annotations

import argparse
from typing import Sequence

from synthran import cli as base_cli
from synthran.experiment import ExperimentError
from synthran.experiment_cli import add_experiment_parser, dispatch_experiment


def _parser() -> argparse.ArgumentParser:
    parser = base_cli._parser()
    subcommands = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    add_experiment_parser(subcommands)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "experiment":
        try:
            return dispatch_experiment(args)
        except (ExperimentError, OSError) as exc:
            parser.error(str(exc))
    return base_cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
