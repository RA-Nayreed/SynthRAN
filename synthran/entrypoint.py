"""Top-level command routing for SynthRAN."""

from __future__ import annotations

import sys
from typing import Sequence

from synthran.cli import main as core_main
from synthran.r2lab import main as r2lab_main


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "r2lab":
        return r2lab_main(args[1:])
    return core_main(args)
