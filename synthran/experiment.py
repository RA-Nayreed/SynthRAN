"""Invoke an explicitly configured experiment without knowing its workload."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .scenario import load_scenario


def invoke(phase: str, config: str | Path, **options) -> None:
    selection = load_scenario(config).get("experiment")
    if not selection:
        if options.get("prepared_workload"):
            raise ValueError("--prepared-workload requires a configured experiment")
        return
    entrypoint = selection.get("entrypoint")
    if not entrypoint or not Path(entrypoint).is_file():
        raise ValueError(
            "experiment.entrypoint must name an existing Python entrypoint"
        )
    command = [
        sys.executable,
        entrypoint,
        phase,
        "--config",
        str(Path(config).resolve()),
    ]
    for name, value in options.items():
        if value:
            command.extend(["--" + name.replace("_", "-"), str(Path(value).resolve())])
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase", choices=("prepare", "run", "cleanup", "finalize", "configure")
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-dir")
    parser.add_argument("--prepared-workload")
    parser.add_argument("--resume-from")
    parser.add_argument("--source-config")
    args = vars(parser.parse_args())
    try:
        invoke(args.pop("phase"), args.pop("config"), **args)
    except (ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
