from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from synthran.resources.live_inventory import read_resource_inventory, resource_inventory_view
from synthran.workspace.access import ProbeResult
from synthran.workspace.model import Profile, WorkspaceError, format_utc
from synthran.workspace.store import initialize_workspace, save_profile


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)


class LiveResourceInventoryTests(unittest.TestCase):
    def _workspace(self, base: Path) -> tuple[Path, dict[str, str]]:
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
        return root, environment

    def _runner(self, allocations):
        calls: list[tuple[str, ...]] = []

        def runner(command, timeout):
            command = tuple(command)
            calls.append(command)
            if command == ("slices", "auth", "show"):
                return ProbeResult(0, "Logged in as operator")
            if command == ("slices", "project", "show"):
                return ProbeResult(
                    0,
                    "The current project is research-project. You are a member. It expires on 2026-10-22 23:59 UTC.",
                )
            if command == ("pos", "allocations", "list", "--json"):
                return ProbeResult(0, json.dumps(allocations))
            raise AssertionError(command)

        return runner, calls

    def test_unallocated_catalog_nodes_remain_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, environment = self._workspace(Path(temporary))
            runner, calls = self._runner([])
            inventory = read_resource_inventory(
                start=root,
                environment=environment,
                runner=runner,
                now=NOW,
            )
            state = inventory.state("sopnode-f2")
            self.assertIsNotNone(state)
            self.assertEqual(state.availability, "unknown")
            self.assertEqual(state.ownership, "unknown")
            self.assertFalse(state.selectable)
            self.assertFalse(inventory.snapshot("slices").complete)
            self.assertEqual(
                calls,
                [
                    ("slices", "auth", "show"),
                    ("slices", "project", "show"),
                    ("pos", "allocations", "list", "--json"),
                ],
            )

    def test_allocated_nodes_report_reduced_ownership_only(self) -> None:
        allocations = [
            {"id": "private-a", "owner": "operator", "nodes": ["sopnode-f2"]},
            {"id": "private-b", "owner": "someone-else", "nodes": ["sopnode-f3"]},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root, environment = self._workspace(Path(temporary))
            runner, _ = self._runner(allocations)
            inventory = read_resource_inventory(
                start=root,
                environment=environment,
                runner=runner,
                now=NOW,
            )
            own = inventory.state("sopnode-f2")
            foreign = inventory.state("sopnode-f3")
            self.assertEqual((own.availability, own.ownership), ("allocated", "operator"))
            self.assertEqual((foreign.availability, foreign.ownership), ("allocated", "other"))

            rendered = json.dumps(resource_inventory_view(inventory, now=NOW))
            self.assertNotIn("private-a", rendered)
            self.assertNotIn("private-b", rendered)
            self.assertNotIn("someone-else", rendered)

    def test_virtual_rfsim_is_local_available_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, environment = self._workspace(Path(temporary))
            runner, _ = self._runner([])
            inventory = read_resource_inventory(
                start=root,
                environment=environment,
                runner=runner,
                now=NOW,
            )
            state = inventory.state("virtual:rfsim")
            self.assertEqual((state.availability, state.ownership), ("available", "unowned"))
            self.assertTrue(state.selectable)

    def test_r2lab_catalog_is_not_promoted_without_resource_specific_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, environment = self._workspace(Path(temporary))
            runner, _ = self._runner([])
            inventory = read_resource_inventory(
                start=root,
                environment=environment,
                runner=runner,
                now=NOW,
            )
            view = resource_inventory_view(inventory, now=NOW)
            r2lab = next(item for item in view["providers"] if item["provider"] == "r2lab")
            radio = next(item for item in view["resources"] if item["resource_id"] == "n300")
            self.assertFalse(r2lab["fresh"])
            self.assertFalse(r2lab["complete"])
            self.assertEqual(radio["availability"], "unknown")
            self.assertEqual(radio["ownership"], "unknown")
            self.assertFalse(radio["selectable"])

    def test_duplicate_reviewed_node_in_allocations_fails_closed(self) -> None:
        allocations = [
            {"owner": "operator", "nodes": ["sopnode-f2"]},
            {"owner": "operator", "nodes": ["sopnode-f2"]},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root, environment = self._workspace(Path(temporary))
            runner, _ = self._runner(allocations)
            with self.assertRaisesRegex(WorkspaceError, "multiple allocations"):
                read_resource_inventory(
                    start=root,
                    environment=environment,
                    runner=runner,
                    now=NOW,
                )

    def test_malformed_allocation_inventory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, environment = self._workspace(Path(temporary))

            def runner(command, timeout):
                command = tuple(command)
                if command == ("slices", "auth", "show"):
                    return ProbeResult(0, "Logged in as operator")
                if command == ("slices", "project", "show"):
                    return ProbeResult(
                        0,
                        "The current project is research-project. You are a member. It expires on 2026-10-22 23:59 UTC.",
                    )
                if command == ("pos", "allocations", "list", "--json"):
                    return ProbeResult(0, "not-json")
                raise AssertionError(command)

            with self.assertRaisesRegex(WorkspaceError, "did not return JSON"):
                read_resource_inventory(
                    start=root,
                    environment=environment,
                    runner=runner,
                    now=NOW,
                )


if __name__ == "__main__":
    unittest.main()
