"""In-memory terminal session state and application request routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from synthran.app.model import ApplicationSnapshot
from synthran.operations.model import OperationEvent
from synthran.terminal.commands import (
    CommandRequest,
    TerminalCommandError,
    parse_command,
    render_help,
    require_command_allowed,
)
from synthran.terminal.render import (
    render_inspect,
    render_operation_event,
    render_status,
)


LINE_KINDS = frozenset({"command", "result", "system", "error"})
RESPONSE_ACTIONS = frozenset({"render", "dispatch", "clear", "quit", "error"})


class TerminalApplication(Protocol):
    def snapshot(self) -> ApplicationSnapshot: ...

    def operation_events(self, operation_id: str) -> tuple[OperationEvent, ...]: ...


@dataclass(frozen=True)
class TerminalLine:
    kind: str
    text: str

    def __post_init__(self) -> None:
        if self.kind not in LINE_KINDS:
            raise TerminalCommandError("terminal line kind is unsupported")
        if not isinstance(self.text, str) or len(self.text) > 1024:
            raise TerminalCommandError("terminal line is malformed")
        if any(character in "\r\n\x00" for character in self.text):
            raise TerminalCommandError("terminal line must contain exactly one safe line")


@dataclass(frozen=True)
class TerminalResponse:
    action: str
    lines: tuple[TerminalLine, ...] = ()
    request: CommandRequest | None = None

    def __post_init__(self) -> None:
        if self.action not in RESPONSE_ACTIONS:
            raise TerminalCommandError("terminal response action is unsupported")
        if self.action == "dispatch" and self.request is None:
            raise TerminalCommandError("dispatch response requires a command request")
        if self.action != "dispatch" and self.request is not None:
            raise TerminalCommandError("only dispatch response may carry a command request")


class TerminalSession:
    """Session-first command surface with no provider command execution."""

    def __init__(self, application: TerminalApplication):
        self.application = application
        self.mode = "observe"
        self.closed = False
        self._transcript: list[TerminalLine] = []

    @property
    def transcript(self) -> tuple[TerminalLine, ...]:
        return tuple(self._transcript)

    def _append(self, kind: str, lines: tuple[str, ...]) -> tuple[TerminalLine, ...]:
        rendered = tuple(TerminalLine(kind, line) for line in lines)
        self._transcript.extend(rendered)
        return rendered

    @staticmethod
    def _normalized(request: CommandRequest) -> str:
        if request.arguments:
            return request.name + " " + " ".join(request.arguments)
        return request.name

    def _error(self, message: str) -> TerminalResponse:
        lines = self._append("error", (message,))
        return TerminalResponse("error", lines=lines)

    def submit(self, line: str) -> TerminalResponse:
        """Parse and route one slash command; mutating commands are not executed here."""

        if self.closed:
            return self._error("terminal session is closed")
        try:
            request = parse_command(line)
            require_command_allowed(request, self.mode)
        except TerminalCommandError as exc:
            return self._error(str(exc))

        self._append("command", (self._normalized(request),))

        if request.name == "/mode":
            assert request.subcommand is not None
            self.mode = request.subcommand
            lines = self._append("system", (f"Mode: {self.mode.upper()}",))
            return TerminalResponse("render", lines=lines)

        if request.name == "/help":
            lines = self._append("result", render_help())
            return TerminalResponse("render", lines=lines)

        if request.name == "/clear":
            self._transcript.clear()
            return TerminalResponse("clear")

        if request.name == "/quit":
            self.closed = True
            lines = self._append("system", ("Session closed",))
            return TerminalResponse("quit", lines=lines)

        if request.name == "/status":
            lines = self._append("result", render_status(self.application.snapshot()))
            return TerminalResponse("render", lines=lines)

        if request.name == "/inspect":
            assert request.subcommand is not None
            lines = self._append(
                "result",
                render_inspect(self.application.snapshot(), request.subcommand),
            )
            return TerminalResponse("render", lines=lines)

        return TerminalResponse("dispatch", request=request)

    def operation_updates(
        self,
        operation_id: str,
        *,
        after_sequence: int = 0,
    ) -> tuple[TerminalLine, ...]:
        """Append structured operation events after one already-rendered sequence number."""

        if type(after_sequence) is not int or after_sequence < 0:
            raise TerminalCommandError("operation event sequence cursor must be non-negative")
        events = self.application.operation_events(operation_id)
        new_events = tuple(
            event for event in events if event.sequence > after_sequence
        )
        lines: list[TerminalLine] = []
        for event in new_events:
            lines.extend(self._append("result", render_operation_event(event)))
        return tuple(lines)
