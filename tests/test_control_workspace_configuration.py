from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from synthran.control import ControlService
from synthran.workspace.model import Profile, format_utc
from synthran.workspace.store import initialize_workspace, load_workspace, save_profile


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


class ControlWorkspaceConfigurationTests(unittest.TestCase):
    def _service(self, base: Path) -> tuple[Path, ControlService]:
        root = base / "repo"
        root.mkdir()
        config_home = base / "config"
        environment = {"SYNTHRAN_CONFIG_HOME": str(config_home)}
        save_profile(
            Profile(
                name="operator",
                created_at_utc=format_utc(NOW),
                updated_at_utc=format_utc(NOW),
                slices_username="operator",
            ),
            environment=environment,
        )
        initialize_workspace(
            root=root,
            profile="operator",
            project="research-project",
            reservation_minutes=120,
            placement="automatic",
            now=NOW,
        )
        return root, ControlService(start=root, environment=environment)

    def test_configure_workspace_updates_defaults_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary))
            response = service.handle(
                {
                    "v": 4,
                    "id": "configure",
                    "method": "workspace.configure",
                    "params": {
                        "reservation_minutes": 180,
                        "placement": "manual",
                        "expected_reservation_minutes": 120,
                        "expected_placement": "automatic",
                    },
                }
            )
            self.assertTrue(response["ok"])
            self.assertEqual(response["result"]["reservation_minutes"], 180)
            self.assertEqual(response["result"]["placement"], "manual")
            current = load_workspace(root)
            self.assertEqual(current.reservation_minutes, 180)
            self.assertEqual(current.placement, "manual")
            snapshot = service.workspace_snapshot(now=NOW)
            self.assertEqual(snapshot["workspace"]["reservation_minutes"], 180)
            self.assertEqual(snapshot["workspace"]["placement"], "manual")

    def test_stale_expected_values_fail_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary))
            first = service.handle(
                {
                    "v": 4,
                    "id": "first",
                    "method": "workspace.configure",
                    "params": {
                        "reservation_minutes": 180,
                        "placement": "automatic",
                        "expected_reservation_minutes": 120,
                        "expected_placement": "automatic",
                    },
                }
            )
            self.assertTrue(first["ok"])

            stale = service.handle(
                {
                    "v": 4,
                    "id": "stale",
                    "method": "workspace.configure",
                    "params": {
                        "reservation_minutes": 240,
                        "placement": "manual",
                        "expected_reservation_minutes": 120,
                        "expected_placement": "automatic",
                    },
                }
            )
            self.assertFalse(stale["ok"])
            self.assertEqual(stale["error"]["code"], "workspace_error")
            current = load_workspace(root)
            self.assertEqual(current.reservation_minutes, 180)
            self.assertEqual(current.placement, "automatic")

    def test_invalid_request_shape_fails_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary))
            response = service.handle(
                {
                    "v": 4,
                    "id": "bad",
                    "method": "workspace.configure",
                    "params": {
                        "reservation_minutes": 180,
                        "placement": "manual",
                    },
                }
            )
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "invalid_params")
            current = load_workspace(root)
            self.assertEqual(current.reservation_minutes, 120)
            self.assertEqual(current.placement, "automatic")

    def test_boolean_reservation_is_rejected_as_invalid_params(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary))
            response = service.handle(
                {
                    "v": 4,
                    "id": "bad-type",
                    "method": "workspace.configure",
                    "params": {
                        "reservation_minutes": True,
                        "placement": "automatic",
                        "expected_reservation_minutes": 120,
                        "expected_placement": "automatic",
                    },
                }
            )
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "invalid_params")
            self.assertEqual(load_workspace(root).reservation_minutes, 120)


if __name__ == "__main__":
    unittest.main()
