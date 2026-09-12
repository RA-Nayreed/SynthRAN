"""Stop only SynthRAN publisher processes owned by one experiment run."""

from __future__ import annotations

import argparse
import os
import signal
from pathlib import Path


def stop_publishers(marker: str) -> int:
    token = marker.encode()
    stopped = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if (
            token not in cmdline
            or b"Experiment.cli" not in cmdline
            or b"workload" not in cmdline
            or b"replay" not in cmdline
        ):
            continue
        try:
            os.kill(int(entry.name), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            continue
        stopped += 1
    return stopped


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--marker", required=True)
    args = parser.parse_args(argv)
    print(stop_publishers(args.marker))


if __name__ == "__main__":
    main()
