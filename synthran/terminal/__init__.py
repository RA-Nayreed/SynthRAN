"""Terminal command vocabulary, routing, and interactive session surface."""

from synthran.terminal.commands import (
    COMMANDS,
    TERMINAL_MODES,
    CommandRequest,
    CommandSpec,
    TerminalCommandError,
    command_allowed,
    command_spec,
    parse_command,
    render_help,
    require_command_allowed,
)
from synthran.terminal.router import DispatchResult, TerminalCommandRouter
from synthran.terminal.session import TerminalLine, TerminalResponse, TerminalSession
from synthran.terminal.shell import SynthRANCompleter, create_prompt_session, run_terminal

__all__ = [
    "COMMANDS",
    "TERMINAL_MODES",
    "CommandRequest",
    "CommandSpec",
    "DispatchResult",
    "SynthRANCompleter",
    "TerminalCommandError",
    "TerminalCommandRouter",
    "TerminalLine",
    "TerminalResponse",
    "TerminalSession",
    "command_allowed",
    "command_spec",
    "create_prompt_session",
    "parse_command",
    "render_help",
    "require_command_allowed",
    "run_terminal",
]
