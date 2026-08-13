from __future__ import annotations

from pathlib import Path
import unittest

from synthran.dependencies import load_lock
from synthran.slices_controller import (
    ControllerCommandResult,
    SlicesControllerError,
    verify_slices_controller,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ControllerRunner:
    def __init__(
        self,
        *,
        ansible_version: str = "2.20.5",
        pos_version: str = "2.5.35",
        auth_ok: bool = True,
        project: str = "project-test",
        experiment: str = "experiment-test",
    ) -> None:
        self.ansible_version = ansible_version
        self.pos_version = pos_version
        self.auth_ok = auth_ok
        self.project = project
        self.experiment = experiment
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command, _timeout):
        argv = tuple(command)
        self.calls.append(argv)
        if argv == ("ansible-playbook", "--version"):
            return ControllerCommandResult(
                0, f"ansible-playbook [core {self.ansible_version}]\n"
            )
        if argv == ("ansible-galaxy", "--version"):
            return ControllerCommandResult(
                0, f"ansible-galaxy [core {self.ansible_version}]\n"
            )
        if argv == ("pos", "--version"):
            return ControllerCommandResult(0, f"pos {self.pos_version}\n")
        if argv == ("slices", "--version"):
            return ControllerCommandResult(0, "slices 1.4.0\n")
        if argv == ("slices", "auth", "show"):
            return ControllerCommandResult(
                0 if self.auth_ok else 2,
                "authenticated\n" if self.auth_ok else "",
            )
        if argv == ("slices", "project", "show"):
            return ControllerCommandResult(0, f"project: {self.project}\n")
        if argv[:3] == ("slices", "experiment", "show"):
            return ControllerCommandResult(0, f"experiment: {self.experiment}\n")
        return ControllerCommandResult(2, "", "unsupported")


class SlicesControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")

    def verify(self, runner: ControllerRunner | None = None, **overrides):
        arguments = {
            "lock": self.lock,
            "project": "project-test",
            "experiment": "experiment-test",
            "runner": runner or ControllerRunner(),
            "which": lambda _name: "/tool",
            "environment": {"CONDA_DEFAULT_ENV": "synthran"},
            "system_name": "Linux",
            "python_version": "3.12.11",
        }
        arguments.update(overrides)
        return verify_slices_controller(**arguments)

    def test_accepts_exact_locked_controller_and_slices_context(self) -> None:
        report = self.verify()
        self.assertTrue(report.ready)
        self.assertEqual("2.20.5", report.ansible_version)
        self.assertEqual("2.5.35", report.pos_version)
        rendered = report.render()
        self.assertNotIn("project-test", rendered)
        self.assertNotIn("experiment-test", rendered)

    def test_rejects_non_linux_controller(self) -> None:
        with self.assertRaisesRegex(SlicesControllerError, "Linux"):
            self.verify(system_name="Windows")

    def test_rejects_wrong_conda_environment(self) -> None:
        with self.assertRaisesRegex(SlicesControllerError, "synthran"):
            self.verify(environment={"CONDA_DEFAULT_ENV": "base"})

    def test_rejects_python_or_ansible_version_drift(self) -> None:
        with self.assertRaisesRegex(SlicesControllerError, "Python"):
            self.verify(python_version="3.12.10")
        with self.assertRaisesRegex(SlicesControllerError, "ansible-core"):
            self.verify(runner=ControllerRunner(ansible_version="2.20.4"))

    def test_rejects_pos_interface_drift(self) -> None:
        with self.assertRaisesRegex(SlicesControllerError, "POS"):
            self.verify(runner=ControllerRunner(pos_version="2.6.0"))

    def test_rejects_missing_authentication(self) -> None:
        with self.assertRaisesRegex(SlicesControllerError, "authentication"):
            self.verify(runner=ControllerRunner(auth_ok=False))

    def test_rejects_project_or_experiment_mismatch(self) -> None:
        with self.assertRaisesRegex(SlicesControllerError, "project"):
            self.verify(runner=ControllerRunner(project="another-project"))
        with self.assertRaisesRegex(SlicesControllerError, "experiment"):
            self.verify(runner=ControllerRunner(experiment="another-experiment"))
        with self.assertRaisesRegex(SlicesControllerError, "project"):
            self.verify(runner=ControllerRunner(project="project-test-extra"))
        with self.assertRaisesRegex(SlicesControllerError, "experiment"):
            self.verify(runner=ControllerRunner(experiment="experiment-test-extra"))

    def test_missing_tool_fails_before_any_probe(self) -> None:
        runner = ControllerRunner()
        with self.assertRaisesRegex(SlicesControllerError, "missing required"):
            self.verify(
                runner=runner,
                which=lambda name: None if name == "slices" else "/tool",
            )
        self.assertEqual([], runner.calls)


if __name__ == "__main__":
    unittest.main()
