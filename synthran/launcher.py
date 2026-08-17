"""Single executable launcher: interactive with no args, scripted CLI with args."""

from __future__ import annotations

import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Open the terminal for an empty argv; otherwise preserve the scripted CLI."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        from synthran.terminal.shell import run_terminal

        return run_terminal()

    from synthran.cli import main as cli_main

    return cli_main(arguments)
