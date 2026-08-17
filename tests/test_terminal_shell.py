from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
import unittest

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from synthran.app.model import ApplicationSnapshot
from synthran.terminal.shell import SynthRANCompleter, run_terminal


class FakeApplication:
    def __init__(self) -> None:
        self.authority = SimpleNamespace(
            workspace=SimpleNamespace(
                project="research-project",
                placement="automatic",
                reservation_minutes=120,
                ownership="strict",
            )
        )

    def snapshot(self) -> ApplicationSnapshot:
        return ApplicationSnapshot(
            workspace_root="/workspace",
            profile="controller",
            project="research-project",
            experiment_id="sran-20260818-001",
            provider_experiment="provider-exp-01",
            intent="iot-to-5g",
            radio_mode="virtual",
            lifecycle="PATH_PROVEN",
        )

    def operation_events(self, operation_id: str):
        return ()


class FakePromptSession:
    def __init__(self, lines: list[str]) -> None:
        self.lines = list(lines)
        self.prompts: list[str] = []

    def prompt(self, message, *, bottom_toolbar=None):
        self.prompts.append(str(message))
        if bottom_toolbar is not None:
            bottom_toolbar()
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


class TerminalShellTests(unittest.TestCase):
    def test_shell_routes_dispatch_and_preserves_inline_session(self) -> None:
        output = StringIO()
        prompt = FakePromptSession(["/config experiment", "/quit"])
        result = run_terminal(
            application=FakeApplication(),  # type: ignore[arg-type]
            prompt_session=prompt,  # type: ignore[arg-type]
            output=output,
            clear_screen=lambda: None,
        )
        self.assertEqual(result, 0)
        text = output.getvalue()
        self.assertIn("SynthRAN interactive terminal", text)
        self.assertIn("Experiment: sran-20260818-001", text)
        self.assertIn("Session closed", text)
        self.assertTrue(prompt.prompts[0].startswith("synthran[OBSERVE]"))

    def test_shell_mode_change_updates_next_prompt(self) -> None:
        output = StringIO()
        prompt = FakePromptSession(["/mode operate", "/quit"])
        result = run_terminal(
            application=FakeApplication(),  # type: ignore[arg-type]
            prompt_session=prompt,  # type: ignore[arg-type]
            output=output,
            clear_screen=lambda: None,
        )
        self.assertEqual(result, 0)
        self.assertTrue(prompt.prompts[0].startswith("synthran[OBSERVE]"))
        self.assertTrue(prompt.prompts[1].startswith("synthran[OPERATE]"))

    def test_completer_uses_command_registry_and_fixed_subcommands(self) -> None:
        completer = SynthRANCompleter()
        commands = [
            item.text
            for item in completer.get_completions(
                Document("/ve"), CompleteEvent(completion_requested=True)
            )
        ]
        self.assertEqual(commands, ["/verify"])

        subcommands = [
            item.text
            for item in completer.get_completions(
                Document("/inspect n"), CompleteEvent(completion_requested=True)
            )
        ]
        self.assertEqual(subcommands, ["network"])


if __name__ == "__main__":
    unittest.main()
