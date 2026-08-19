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

    if arguments[:3] == ["experiment", "research", "campaign-run"]:
        from synthran.research.campaign_runtime import campaign_runtime_session

        session = campaign_runtime_session(arguments)
        with session:
            result = cli_main(arguments)
            session.command_exit_code = result
        if session.cleanup_error is not None:
            print(
                f"[synthran] campaign cleanup failed: {session.cleanup_error}",
                file=sys.stderr,
            )
            return 2
        return result

    return cli_main(arguments)
