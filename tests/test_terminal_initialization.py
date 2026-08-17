from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from synthran.terminal.initialize import initialization_root, initialize_from_terminal
from synthran.workspace.model import WorkspaceConfig


class FakePrompt:
    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.messages: list[str] = []

    def prompt(self, message: str, **kwargs) -> str:
        self.messages.append(message)
        if not self.answers:
            raise AssertionError(f"unexpected prompt: {message}")
        return self.answers.pop(0)


class TerminalInitializationTests(unittest.TestCase):
    def test_initialization_root_prefers_existing_synthran_project_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            child = root / "src" / "nested"
            child.mkdir(parents=True)
            (root / ".synthran").mkdir()
            self.assertEqual(initialization_root(child), root.resolve())

    def test_new_profile_collects_stable_identity_and_keeps_r2lab_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            prompt = FakePrompt(["", "", "operator", "n"])
            output = StringIO()
            workspace = WorkspaceConfig(
                profile="default",
                project="post5g-beta",
                created_at_utc="2026-08-18T00:00:00Z",
            )
            expected = SimpleNamespace(workspace=workspace)

            with patch(
                "synthran.terminal.initialize.initialize_controller_workspace",
                return_value=expected,
            ) as initialize:
                result = initialize_from_terminal(
                    root=root,
                    prompt=prompt,
                    output=output,
                    environment={
                        "SYNTHRAN_CONFIG_HOME": str(base / "config"),
                        "SYNTHRAN_SLICES_PROJECT": "post5g-beta",
                    },
                )

            self.assertIs(result, expected)
            request = initialize.call_args.args[0]
            self.assertEqual(request.root, root.resolve())
            self.assertEqual(request.profile_name, "default")
            self.assertEqual(request.project, "post5g-beta")
            self.assertEqual(request.slices_username, "operator")
            self.assertFalse(request.reuse_profile)
            self.assertIsNone(request.r2lab_slice)
            self.assertIn("Verifying provider access read-only", output.getvalue())

    def test_existing_profile_is_reused_without_reentering_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            config = base / "config"
            profile = config / "profiles" / "default.toml"
            profile.parent.mkdir(parents=True)
            profile.write_text("fixture", encoding="utf-8")
            prompt = FakePrompt(["", "post5g-beta"])
            output = StringIO()
            workspace = WorkspaceConfig(
                profile="default",
                project="post5g-beta",
                created_at_utc="2026-08-18T00:00:00Z",
            )
            expected = SimpleNamespace(workspace=workspace)

            with patch(
                "synthran.terminal.initialize.initialize_controller_workspace",
                return_value=expected,
            ) as initialize:
                initialize_from_terminal(
                    root=root,
                    prompt=prompt,
                    output=output,
                    environment={"SYNTHRAN_CONFIG_HOME": str(config)},
                )

            request = initialize.call_args.args[0]
            self.assertTrue(request.reuse_profile)
            self.assertIsNone(request.slices_username)
            self.assertEqual(len(prompt.messages), 2)
            self.assertIn("Reusing controller profile", output.getvalue())

    def test_existing_legacy_directory_is_announced_not_treated_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            (root / ".synthran" / "runs").mkdir(parents=True)
            prompt = FakePrompt(["", "post5g-beta", "operator", "n"])
            output = StringIO()
            workspace = WorkspaceConfig(
                profile="default",
                project="post5g-beta",
                created_at_utc="2026-08-18T00:00:00Z",
            )
            with patch(
                "synthran.terminal.initialize.initialize_controller_workspace",
                return_value=SimpleNamespace(workspace=workspace),
            ):
                initialize_from_terminal(
                    root=root,
                    prompt=prompt,
                    output=output,
                    environment={"SYNTHRAN_CONFIG_HOME": str(base / "config")},
                )
            self.assertIn("legacy artifacts will be preserved", output.getvalue())


if __name__ == "__main__":
    unittest.main()
