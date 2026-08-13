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

    def test_privacy_steps_run_after_unrelated_test_failure(self) -> None:
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "privacy.yml"
        ).read_text(encoding="utf-8")
        source_scan = (
            "      - name: Scan tracked source for private context\n"
            "        run: conda run --no-capture-output -n synthran "
            "python -m synthran privacy scan --worktree\n"
            "        if: ${{ !cancelled() }}\n"
        )
        history_scan = (
            "      - name: Scan Git history for secrets\n"
            "        if: ${{ !cancelled() }}\n"
            "        uses: gitleaks/gitleaks-action@"
            "e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e\n"
            "        env:\n"
            "          GITHUB_TOKEN: ${{ github.token }}\n"
        )
        self.assertIn(source_scan, workflow)
        self.assertIn(history_scan, workflow)

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

    def test_linux_environment_matches_direct_conda_lock(self) -> None:
        lock = json.loads((REPOSITORY_ROOT / "dependencies.lock.yml").read_text())
        environment = (REPOSITORY_ROOT / "environment.yml").read_text(encoding="utf-8")
        self.assertEqual("linux-64", lock["conda"]["platform"])
        self.assertEqual(
            ["environment.yml"],
            sorted(path.name for path in REPOSITORY_ROOT.glob("environment*.yml")),
        )
        self.assertIn(f"name: {lock['conda']['environment_name']}", environment)
        for channel in lock["conda"]["channels"]:
            self.assertIn(f"  - {channel}", environment)
        expected = {
            f"{package}={entry['version']}"
            for package, entry in lock["conda"]["packages"].items()
        }
        dependencies = environment.split("dependencies:\n", 1)[1]
        actual = {
            line.removeprefix("  - ")
            for line in dependencies.splitlines()
            if line.startswith("  - ")
        }
        self.assertEqual(expected, actual)

    def test_pre_push_hook_uses_linux_conda_without_python_fallback(self) -> None:
        hook = (REPOSITORY_ROOT / ".githooks" / "pre-push").read_text(
            encoding="utf-8"
        )
        self.assertIn('"$conda_command" run --no-capture-output', hook)
        self.assertIn("SYNTHRAN_CONDA_EXE", hook)
        self.assertIn("SYNTHRAN_CONDA_ENV", hook)
        self.assertIn("command -v conda", hook)
        self.assertNotIn("conda.exe", hook)
        self.assertNotIn("SYNTHRAN_PYTHON", hook)
        self.assertNotIn("command -v python", hook)

    def test_decision_journal_is_not_in_tracked_ignore_rules(self) -> None:
        ignore_rules = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("decision.md", ignore_rules)

    def test_build_backend_is_exactly_pinned(self) -> None:
        project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
        requirements = project["build-system"]["requires"]
        self.assertEqual(["setuptools==83.0.0"], requirements)

    def test_readme_is_a_project_landing_page_with_focused_docs(self) -> None:
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Why SynthRAN exists", readme)
        self.assertIn("```mermaid", readme)
        self.assertIn("Current status", readme)
        self.assertIn("Planned experiment output", readme)
        for name in (
            "architecture.md",
            "operator-guide.md",
            "development.md",
            "dependencies.md",
            "security.md",
        ):
            self.assertTrue((REPOSITORY_ROOT / "docs" / name).is_file(), name)
            self.assertIn(f"docs/{name}", readme)

    def test_numbered_phase_terms_exist_only_in_the_decision_journal(self) -> None:
        excluded_parts = {".git", ".deps", ".synthran", "__pycache__"}
        pattern = re.compile(r"phase[\s_-]*[012]", flags=re.IGNORECASE)
        for path in REPOSITORY_ROOT.rglob("*"):
            if (
                not path.is_file()
                or path.name == "decision.md"
                or excluded_parts.intersection(path.relative_to(REPOSITORY_ROOT).parts)
            ):
                continue
            relative = path.relative_to(REPOSITORY_ROOT).as_posix()
            self.assertIsNone(pattern.search(relative), relative)
            if path.suffix.lower() in {
                ".ini",
                ".json",
                ".md",
                ".py",
                ".sh",
                ".toml",
                ".txt",
                ".yaml",
                ".yml",
            } or path.name in {"AGENTS.md", "LICENSE", "README.md", "THIRD_PARTY.md"}:
                content = path.read_text(encoding="utf-8")
                self.assertIsNone(pattern.search(content), relative)

    def test_interactive_guides_use_direct_commands_after_activation(self) -> None:
        paths = (
            REPOSITORY_ROOT / "README.md",
            REPOSITORY_ROOT / "docs" / "dependencies.md",
            REPOSITORY_ROOT / "docs" / "development.md",
            REPOSITORY_ROOT / "docs" / "operator-guide.md",
            REPOSITORY_ROOT / "docs" / "security.md",
        )
        for path in paths:
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("conda run", content, str(path))
        self.assertIn("conda activate synthran", paths[0].read_text(encoding="utf-8"))
        self.assertIn("conda activate synthran", paths[2].read_text(encoding="utf-8"))
        self.assertIn("conda activate synthran", paths[3].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
