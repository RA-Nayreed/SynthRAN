from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class FoundationTests(unittest.TestCase):
    def test_workflow_actions_match_lock_and_use_full_shas(self) -> None:
        lock = json.loads((REPOSITORY_ROOT / "dependencies.lock.yml").read_text())
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "privacy.yml"
        ).read_text(encoding="utf-8")
        uses = re.findall(r"^\s*uses:\s*([^\s]+)\s*$", workflow, flags=re.MULTILINE)
        self.assertEqual(3, len(uses))
        self.assertTrue(all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", item) for item in uses))
        for entry in lock["github_actions"].values():
            expected = f"{entry['repository']}@{entry['commit']}"
            self.assertIn(expected, uses)

    def test_workflow_is_read_only_and_does_not_persist_credentials(self) -> None:
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "privacy.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("fetch-depth: 0", workflow)

    def test_workflow_uses_the_locked_conda_environment(self) -> None:
        lock = json.loads((REPOSITORY_ROOT / "dependencies.lock.yml").read_text())
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "privacy.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("environment-file: environment.yml", workflow)
        self.assertIn(
            f"miniforge-version: \"{lock['conda']['installer']['version']}\"",
            workflow,
        )
        self.assertIn("conda run --no-capture-output -n synthran", workflow)
        self.assertNotIn("actions/setup-python", workflow)

    def test_environment_matches_direct_conda_lock(self) -> None:
        lock = json.loads((REPOSITORY_ROOT / "dependencies.lock.yml").read_text())
        environment = (REPOSITORY_ROOT / "environment.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"name: {lock['conda']['environment_name']}", environment)
        for channel in lock["conda"]["channels"]:
            self.assertIn(f"  - {channel}", environment)
        for package, entry in lock["conda"]["packages"].items():
            self.assertIn(f"  - {package}={entry['version']}", environment)

    def test_pre_push_hook_uses_conda_without_python_fallback(self) -> None:
        hook = (REPOSITORY_ROOT / ".githooks" / "pre-push").read_text(
            encoding="utf-8"
        )
        self.assertIn('"$conda_command" run --no-capture-output', hook)
        self.assertIn("SYNTHRAN_CONDA_EXE", hook)
        self.assertIn("SYNTHRAN_CONDA_ENV", hook)
        self.assertIn("LOCALAPPDATA", hook)
        self.assertIn("USERPROFILE", hook)
        self.assertIn("anaconda3 miniconda3 miniforge3", hook)
        self.assertNotIn("SYNTHRAN_PYTHON", hook)
        self.assertNotIn("command -v python", hook)

    def test_decision_journal_is_not_in_tracked_ignore_rules(self) -> None:
        ignore_rules = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("decision.md", ignore_rules)

    def test_build_backend_is_exactly_pinned(self) -> None:
        project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
        requirements = project["build-system"]["requires"]
        self.assertEqual(["setuptools==83.0.0"], requirements)


if __name__ == "__main__":
    unittest.main()
