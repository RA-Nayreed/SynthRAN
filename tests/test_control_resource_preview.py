from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from synthran.control import ControlService
from synthran.resources.model import ResourceSelectionError
from synthran.resources.slices_inventory import InventoryCommandResult
from synthran.workspace.model import AccessRecord, Profile, WorkspaceError, format_utc
from synthran.workspace.store import initialize_workspace, save_access_record, save_profile


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


class PreviewRunner:
    def __init__(self, *, reservations=None, allocations=None):
        self.reservations = [] if reservations is None else reservations
        self.allocations = [] if allocations is None else allocations
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command, _timeout):
        argv = tuple(command)
        self.calls.append(argv)
        if argv == ("pos", "calendar", "list", "--json"):
            return InventoryCommandResult(0, json.dumps(self.reservations))
        if argv == ("pos", "allocations", "list", "--json"):
            return InventoryCommandResult(0, json.dumps(self.allocations))
        raise AssertionError(f"unexpected command: {argv}")


class ResourcePreviewControlTests(unittest.TestCase):
    def _service(self, base: Path, runner: PreviewRunner) -> tuple[Path, ControlService]:
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
        return root, ControlService(
            start=root,
            environment=environment,
            inventory_runner=runner,
        )

    def _fresh_access(self, root: Path) -> None:
        save_access_record(
            root,
            AccessRecord(
                provider="slices",
                subject="operator",
                scope="research-project",
                verified_at_utc=format_utc(NOW - timedelta(minutes=5)),
                refresh_after_utc=format_utc(NOW + timedelta(hours=1)),
                access_until_utc=format_utc(NOW + timedelta(days=1)),
            ),
        )

    def test_virtual_preview_uses_live_compute_state_and_virtual_radio(self) -> None:
        runner = PreviewRunner()
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary), runner)
            self._fresh_access(root)
            service.create_experiment(
                {"intent": "virtual-5g", "radio_mode": "virtual"},
                now=NOW,
            )

            preview = service.resource_preview(now=NOW)
            self.assertTrue(preview["inventory"]["complete"])
            self.assertEqual("slices", preview["inventory"]["provider"])
            self.assertEqual(4, len(preview["inventory"]["resources"]))

            assignments = {
                item["role"]: item["resource_id"]
                for item in preview["decision"]["selection"]["assignments"]
            }
            self.assertEqual("sopnode-f2", assignments["core"])
            self.assertEqual("sopnode-f3", assignments["ran"])
            self.assertEqual("virtual:rfsim", assignments["radio"])
            self.assertEqual(
                [
                    ("pos", "calendar", "list", "--json"),
                    ("pos", "allocations", "list", "--json"),
                ],
                runner.calls,
            )

    def test_stale_access_blocks_before_any_pos_read(self) -> None:
        runner = PreviewRunner()
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary), runner)
            save_access_record(
                root,
                AccessRecord(
                    provider="slices",
                    subject="operator",
                    scope="research-project",
                    verified_at_utc=format_utc(NOW - timedelta(hours=2)),
                    refresh_after_utc=format_utc(NOW - timedelta(hours=1)),
                    access_until_utc=format_utc(NOW + timedelta(days=1)),
                ),
            )
            service.create_experiment(
                {"intent": "virtual-5g", "radio_mode": "virtual"},
                now=NOW,
            )

            with self.assertRaisesRegex(WorkspaceError, "stale"):
                service.resource_preview(now=NOW)
            self.assertEqual([], runner.calls)

    def test_physical_preview_fails_without_live_r2lab_inventory(self) -> None:
        runner = PreviewRunner()
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary), runner)
            self._fresh_access(root)
            service.create_experiment(
                {"intent": "physical-5g", "radio_mode": "physical"},
                now=NOW,
            )

            with self.assertRaisesRegex(
                ResourceSelectionError,
                "complete r2lab resource inventory",
            ):
                service.resource_preview(now=NOW)
            self.assertEqual(2, len(runner.calls))

    def test_foreign_allocation_is_excluded_from_selected_placement(self) -> None:
        runner = PreviewRunner(
            allocations=[
                {"id": "foreign", "owner": "other-user", "nodes": ["sopnode-f2"]}
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary), runner)
            self._fresh_access(root)
            service.create_experiment(
                {"intent": "virtual-5g", "radio_mode": "virtual"},
                now=NOW,
            )

            preview = service.resource_preview(now=NOW)
            selected = {
                item["resource_id"]
                for item in preview["decision"]["selection"]["assignments"]
            }
            self.assertNotIn("sopnode-f2", selected)

    def test_preview_params_fail_before_provider_read(self) -> None:
        runner = PreviewRunner()
        with tempfile.TemporaryDirectory() as temporary:
            _, service = self._service(Path(temporary), runner)
            response = service.handle(
                {
                    "v": 3,
                    "id": "preview",
                    "method": "resources.preview",
                    "params": {"refresh": True},
                }
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_params", response["error"]["code"])
            self.assertEqual([], runner.calls)


if __name__ == "__main__":
    unittest.main()
