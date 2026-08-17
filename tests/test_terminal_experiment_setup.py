from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from synthran.app.model import ApplicationSnapshot
from synthran.terminal.experiment_setup import ensure_active_experiment


class FakePrompt:
    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.messages: list[str] = []

    def prompt(self, message: str, **kwargs) -> str:
        self.messages.append(message)
        if not self.answers:
            raise AssertionError(f"unexpected prompt: {message}")
        return self.answers.pop(0)


def snapshot(experiment_id: str | None) -> ApplicationSnapshot:
    return ApplicationSnapshot(
        workspace_root="/workspace",
        profile="default",
        project="post5g-beta",
        experiment_id=experiment_id,
        provider_experiment=None,
        intent=None,
        radio_mode=None,
        lifecycle="EMPTY" if experiment_id is None else "CONFIGURED",
    )


class TerminalExperimentSetupTests(unittest.TestCase):
    def test_existing_active_experiment_is_left_untouched(self) -> None:
        application = Mock()
        application.snapshot.return_value = snapshot("sran-20260818-001")
        prompt = FakePrompt([])
        result = ensure_active_experiment(
            application=application,
            prompt=prompt,
            output=StringIO(),
        )
        self.assertIsNone(result)
        application.create_experiment.assert_not_called()

    def test_operator_can_leave_initialized_workspace_empty(self) -> None:
        application = Mock()
        application.snapshot.return_value = snapshot(None)
        prompt = FakePrompt(["n"])
        result = ensure_active_experiment(
            application=application,
            prompt=prompt,
            output=StringIO(),
        )
        self.assertIsNone(result)
        application.create_experiment.assert_not_called()

    def test_default_setup_creates_iot_rfsim_experiment_and_uses_provider_env_default(self) -> None:
        application = Mock()
        application.snapshot.return_value = snapshot(None)
        record = SimpleNamespace(
            experiment_id="sran-20260818-001",
            slices_experiment="provider-exp-01",
        )
        application.create_experiment.return_value = record
        prompt = FakePrompt(["", "", "", "", ""])
        output = StringIO()

        result = ensure_active_experiment(
            application=application,
            prompt=prompt,
            output=output,
            environment={"SYNTHRAN_SLICES_EXPERIMENT": "provider-exp-01"},
        )

        self.assertIs(result, record)
        call = application.create_experiment.call_args.kwargs
        desired = call["desired"]
        self.assertEqual(desired.intent, "iot-to-5g")
        self.assertEqual(desired.radio.mode, "virtual")
        self.assertEqual(desired.radio.backend, "rfsim")
        self.assertEqual(call["slices_experiment"], "provider-exp-01")
        self.assertTrue(call["activate"])
        self.assertIn("Active experiment created", output.getvalue())

    def test_blank_provider_binding_is_explicitly_reported(self) -> None:
        application = Mock()
        application.snapshot.return_value = snapshot(None)
        record = SimpleNamespace(
            experiment_id="sran-20260818-001",
            slices_experiment=None,
        )
        application.create_experiment.return_value = record
        prompt = FakePrompt(["y", "iot-to-5g", "virtual", "", ""])
        output = StringIO()

        ensure_active_experiment(
            application=application,
            prompt=prompt,
            output=output,
            environment={},
        )

        self.assertIsNone(
            application.create_experiment.call_args.kwargs["slices_experiment"]
        )
        self.assertIn("live control will remain fail-closed", output.getvalue())

    def test_physical_selection_maps_to_r2lab_backend(self) -> None:
        application = Mock()
        application.snapshot.return_value = snapshot(None)
        application.create_experiment.return_value = SimpleNamespace(
            experiment_id="sran-20260818-001",
            slices_experiment="provider-exp-01",
        )
        prompt = FakePrompt(["y", "physical-5g", "physical", "provider-exp-01", ""])

        ensure_active_experiment(
            application=application,
            prompt=prompt,
            output=StringIO(),
            environment={},
        )

        desired = application.create_experiment.call_args.kwargs["desired"]
        self.assertEqual(desired.radio.mode, "physical")
        self.assertEqual(desired.radio.backend, "r2lab")


if __name__ == "__main__":
    unittest.main()
