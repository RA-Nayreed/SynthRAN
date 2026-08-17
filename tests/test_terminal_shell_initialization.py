from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from synthran.app.model import ApplicationSnapshot
from synthran.terminal.shell import run_terminal
from synthran.workspace.model import WorkspaceError


class FakeApplication:
    def __init__(self) -> None:
        self.authority = SimpleNamespace(
            workspace=SimpleNamespace(
                project="post5g-beta",
                placement="automatic",
                reservation_minutes=120,
                ownership="strict",
            )
        )

    def snapshot(self) -> ApplicationSnapshot:
        return ApplicationSnapshot(
            workspace_root="/workspace",
            profile="default",
            project="post5g-beta",
            experiment_id=None,
            provider_experiment=None,
            intent=None,
            radio_mode=None,
            lifecycle="EMPTY",
        )

    def operation_events(self, operation_id: str):
        return ()


class FakePrompt:
    def __init__(self, lines: list[str]) -> None:
        self.lines = list(lines)

    def prompt(self, message, **kwargs):
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


class TerminalShellInitializationTests(unittest.TestCase):
    def test_missing_workspace_runs_verified_initializer_then_reopens_application(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = StringIO()
            prompt = FakePrompt(["n", "/quit"])
            app = FakeApplication()
            with patch(
                "synthran.terminal.shell.ApplicationController",
                side_effect=[WorkspaceError("no SynthRAN workspace was found"), app],
            ) as controller, patch(
                "synthran.terminal.shell.initialize_from_terminal"
            ) as initialize:
                result = run_terminal(
                    start=root,
                    prompt_session=prompt,  # type: ignore[arg-type]
                    output=output,
                    clear_screen=lambda: None,
                )

            self.assertEqual(result, 0)
            initialize.assert_called_once()
            self.assertEqual(initialize.call_args.kwargs["root"], root.resolve())
            self.assertEqual(controller.call_count, 2)
            self.assertIn("SynthRAN interactive terminal", output.getvalue())

    def test_failed_initialization_returns_without_starting_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = StringIO()
            prompt = FakePrompt([])
            with patch(
                "synthran.terminal.shell.ApplicationController",
                side_effect=WorkspaceError("no SynthRAN workspace was found"),
            ), patch(
                "synthran.terminal.shell.initialize_from_terminal",
                side_effect=WorkspaceError("SLICES access verification failed"),
            ):
                result = run_terminal(
                    start=root,
                    prompt_session=prompt,  # type: ignore[arg-type]
                    output=output,
                    clear_screen=lambda: None,
                )

            self.assertEqual(result, 2)
            self.assertIn("SLICES access verification failed", output.getvalue())
            self.assertIn("no provider resource mutation was attempted", output.getvalue())


if __name__ == "__main__":
    unittest.main()
