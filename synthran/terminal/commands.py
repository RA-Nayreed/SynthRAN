"""Strict slash-command vocabulary shared by terminal parsing and policy."""

from __future__ import annotations

from dataclasses import dataclass
import shlex

from synthran.workspace.model import WorkspaceError


TERMINAL_MODES = frozenset({"observe", "operate"})
TERMINAL_RISKS = frozenset({"R0", "R1", "R2", "R3"})


class TerminalCommandError(WorkspaceError):
    """Raised when terminal input is outside the explicit command contract."""


@dataclass(frozen=True)
class CommandSpec:
    name: str
    risk: str
    description: str
    mutates: bool = False
    subcommands: tuple[str, ...] = ()
    arguments_required: bool = False

    def __post_init__(self) -> None:
        if not self.name.startswith("/") or len(self.name) < 2:
            raise TerminalCommandError("terminal command name must begin with '/'")
        if self.risk not in TERMINAL_RISKS:
            raise TerminalCommandError("terminal command risk is unsupported")
        if self.mutates and self.risk not in {"R2", "R3"}:
            raise TerminalCommandError("mutating terminal command must use R2 or R3")
        if not self.mutates and self.risk in {"R2", "R3"}:
            raise TerminalCommandError("R2/R3 terminal command must be marked mutating")
        if not self.description or len(self.description) > 160:
            raise TerminalCommandError("terminal command description is malformed")
        if len(set(self.subcommands)) != len(self.subcommands):
            raise TerminalCommandError("terminal command subcommands must be unique")
        for value in self.subcommands:
            if not value or len(value) > 32 or any(
                not (character.isalnum() or character in "._-")
                for character in value
            ):
                raise TerminalCommandError("terminal subcommand contains unsafe characters")


@dataclass(frozen=True)
class CommandRequest:
    spec: CommandSpec
    arguments: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def subcommand(self) -> str | None:
        return self.arguments[0] if self.spec.subcommands and self.arguments else None


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("/status", "R0", "show the current workspace and experiment status"),
    CommandSpec(
        "/inspect",
        "R0",
        "inspect reconciled resource or network state",
        subcommands=("resources", "network"),
        arguments_required=True,
    ),
    CommandSpec("/reserve", "R2", "reserve the selected testbed resources", mutates=True),
    CommandSpec("/up", "R2", "bring the requested network toward ready state", mutates=True),
    CommandSpec("/verify", "R1", "verify the current end-to-end network path"),
    CommandSpec("/recover", "R2", "reconcile and recover owned incomplete state", mutates=True),
    CommandSpec("/down", "R3", "tear down only the explicitly owned experiment resources", mutates=True),
    CommandSpec(
        "/run",
        "R2",
        "start a controlled experiment condition",
        mutates=True,
        subcommands=("baseline", "congestion"),
        arguments_required=True,
    ),
    CommandSpec("/stop", "R2", "stop the active controlled experiment", mutates=True),
    CommandSpec("/collect", "R1", "collect and validate experiment evidence"),
    CommandSpec(
        "/logs",
        "R1",
        "read sanitized component logs",
        subcommands=("network", "open5gs", "ue"),
        arguments_required=True,
    ),
    CommandSpec(
        "/config",
        "R0",
        "show durable resource or experiment configuration",
        subcommands=("resources", "experiment"),
        arguments_required=True,
    ),
    CommandSpec(
        "/mode",
        "R0",
        "switch terminal mutation policy",
        subcommands=("observe", "operate"),
        arguments_required=True,
    ),
    CommandSpec("/help", "R0", "show the command vocabulary"),
    CommandSpec("/clear", "R0", "clear the visible terminal transcript"),
    CommandSpec("/quit", "R0", "leave the terminal session"),
)

COMMAND_BY_NAME = {item.name: item for item in COMMANDS}


def command_spec(name: str) -> CommandSpec:
    try:
        return COMMAND_BY_NAME[name]
    except KeyError as exc:
        raise TerminalCommandError(f"unknown terminal command: {name}") from exc


def parse_command(line: str) -> CommandRequest:
    """Parse one explicit slash command without natural-language interpretation."""

    if not isinstance(line, str):
        raise TerminalCommandError("terminal input must be text")
    stripped = line.strip()
    if not stripped:
        raise TerminalCommandError("terminal command must not be empty")
    if not stripped.startswith("/"):
        raise TerminalCommandError("terminal accepts explicit slash commands only")
    try:
        parts = shlex.split(stripped, posix=True)
    except ValueError as exc:
        raise TerminalCommandError("terminal command quoting is malformed") from exc
    if not parts:
        raise TerminalCommandError("terminal command must not be empty")
    spec = command_spec(parts[0])
    arguments = tuple(parts[1:])

    if spec.subcommands:
        if not arguments:
            if spec.arguments_required:
                choices = ", ".join(spec.subcommands)
                raise TerminalCommandError(
                    f"{spec.name} requires one of: {choices}"
                )
        else:
            if arguments[0] not in spec.subcommands:
                choices = ", ".join(spec.subcommands)
                raise TerminalCommandError(
                    f"{spec.name} subcommand must be one of: {choices}"
                )
            if len(arguments) != 1:
                raise TerminalCommandError(
                    f"{spec.name} accepts exactly one subcommand"
                )
    elif arguments:
        raise TerminalCommandError(f"{spec.name} does not accept inline arguments")

    return CommandRequest(spec=spec, arguments=arguments)


def command_allowed(request: CommandRequest, mode: str) -> bool:
    """Return whether the terminal mode permits the command to proceed to policy."""

    if mode not in TERMINAL_MODES:
        raise TerminalCommandError("terminal mode is unsupported")
    if mode == "observe" and request.spec.mutates:
        return False
    return True


def require_command_allowed(request: CommandRequest, mode: str) -> None:
    if not command_allowed(request, mode):
        raise TerminalCommandError(
            f"{request.name} requires OPERATE mode; current mode is OBSERVE"
        )


def render_help() -> tuple[str, ...]:
    """Return stable compact help lines for inline terminal rendering."""

    lines: list[str] = []
    for item in COMMANDS:
        suffix = ""
        if item.subcommands:
            suffix = " " + "|".join(item.subcommands)
        lines.append(f"{item.name}{suffix}  [{item.risk}]  {item.description}")
    return tuple(lines)
