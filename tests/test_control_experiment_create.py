from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from synthran.control import ControlService
from synthran.workspace.desired_store import load_desired_state
from synthran.workspace.model import Profile, format_utc
from synthran.workspace.store import (
    initialize_workspace,
    load_active_experiment_id,
    save_profile,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)


class ControlExperimentCreateTests(unittest.TestCase):
    def _service(self, base: Path) -> tuple[Path, ControlService]:
        root = base / "repo"
        root.mkdir()
        config_home = base / "config"
        environment = {"SYNTHRAN_CONFIG_HOME": str(config_home)}
        save_profile(
            Profile(
                name="controller",
                created_at_utc=format_utc(NOW),
                updated_at_utc=format_utc(NOW),
                slices_username="operator",
            ),
            environment=environment,
        )
        initialize_workspace(
            root=root,
            profile="controller",
            project="research-project",
            now=NOW,
        )
        return root, ControlService(start=root, environment=environment)

    def test_create_persists_and_activates_validated_desired_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary))
            response = service.handle(
                {
                    "v": 2,
                    "id": "create-1",
                    "method": "experiment.create",
                    "params": {"intent": "iot-to-5g", "radio_mode": "virtual"},
                }
            )
            self.assertTrue(response["ok"])
            result = response["result"]
            experiment_id = result["experiment_id"]
            self.assertEqual(load_active_experiment_id(root), experiment_id)
            desired = load_desired_state(root, experiment_id)
            self.assertEqual(desired.intent, "iot-to-5g")
            self.assertEqual(desired.radio.mode, "virtual")
            self.assertEqual(desired.radio.backend, "rfsim")
            self.assertEqual(result["snapshot"]["experiment"]["id"], experiment_id)
            self.assertEqual(result["snapshot"]["experiment"]["lifecycle"], "CONFIGURED")

    def test_physical_mode_uses_r2lab_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary))
            result = service.create_experiment(
                {"intent": "physical-5g", "radio_mode": "physical"},
                now=NOW,
            )
            desired = load_desired_state(root, result["experiment_id"])
            self.assertEqual(desired.radio.mode, "physical")
            self.assertEqual(desired.radio.backend, "r2lab")

    def test_incompatible_intent_and_radio_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, service = self._service(Path(temporary))
            response = service.handle(
                {
                    "v": 2,
                    "id": "create-2",
                    "method": "experiment.create",
                    "params": {"intent": "virtual-5g", "radio_mode": "physical"},
                }
            )
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "workspace_error")

    def test_unknown_create_fields_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, service = self._service(Path(temporary))
            response = service.handle(
                {
                    "v": 2,
                    "id": "create-3",
                    "method": "experiment.create",
                    "params": {
                        "intent": "virtual-5g",
                        "radio_mode": "virtual",
                        "extra": "value",
                    },
                }
            )
            self.assertFalse(response["ok"])
            self.assertIn("unsupported fields", response["error"]["message"])

    def test_create_refuses_to_replace_active_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, service = self._service(Path(temporary))
            first = service.handle(
                {
                    "v": 2,
                    "id": "create-4",
                    "method": "experiment.create",
                    "params": {"intent": "virtual-5g", "radio_mode": "virtual"},
                }
            )
            self.assertTrue(first["ok"])
            second = service.handle(
                {
                    "v": 2,
                    "id": "create-5",
                    "method": "experiment.create",
                    "params": {"intent": "iot-to-5g", "radio_mode": "virtual"},
                }
            )
            self.assertFalse(second["ok"])
            self.assertIn("already has an active experiment", second["error"]["message"])


if __name__ == "__main__":
    unittest.main()
