from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from synthran.resources.live_inventory import read_resource_inventory, resource_inventory_view
from synthran.workspace.access import ProbeResult
from synthran.workspace.model import Profile, format_utc
from synthran.workspace.store import initialize_workspace, save_profile


NOW = datetime(2026, 8, 18, 3, 30, tzinfo=timezone.utc)


class ResourceInventoryAuthorityTests(unittest.TestCase):
    def test_incomplete_slices_state_is_never_exposed_as_selectable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            environment = {"SYNTHRAN_CONFIG_HOME": str(base / "config")}
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
                    return ProbeResult(
                        0,
                        '[{"owner":"operator","nodes":["sopnode-f2"]}]',
                    )
                raise AssertionError(command)

            inventory = read_resource_inventory(
                start=root,
                environment=environment,
                runner=runner,
                now=NOW,
            )
            view = resource_inventory_view(inventory, now=NOW)
            slices = next(
                item for item in view["providers"] if item["provider"] == "slices"
            )
            f2 = next(
                item for item in view["resources"] if item["resource_id"] == "sopnode-f2"
            )
            rfsim = next(
                item for item in view["resources"] if item["resource_id"] == "virtual:rfsim"
            )

            self.assertFalse(slices["complete"])
            self.assertEqual(f2["availability"], "allocated")
            self.assertEqual(f2["ownership"], "operator")
            self.assertFalse(f2["selectable"])
            self.assertTrue(rfsim["selectable"])


if __name__ == "__main__":
    unittest.main()
