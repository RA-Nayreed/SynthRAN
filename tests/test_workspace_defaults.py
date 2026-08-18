from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from synthran.workspace.defaults import update_workspace_defaults
from synthran.workspace.model import Profile, WorkspaceError, format_utc
from synthran.workspace.store import initialize_workspace, load_workspace, save_profile


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


class WorkspaceDefaultsTests(unittest.TestCase):
    def _workspace(self, base: Path) -> Path:
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
        return root

    def test_update_preserves_workspace_authority_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._workspace(Path(temporary))
            before = load_workspace(root)
            updated = update_workspace_defaults(
                root,
                reservation_minutes=180,
                placement="manual",
                expected_reservation_minutes=120,
                expected_placement="automatic",
            )
            after = load_workspace(root)

            self.assertEqual(updated, after)
            self.assertEqual(180, after.reservation_minutes)
            self.assertEqual("manual", after.placement)
            self.assertEqual(before.profile, after.profile)
            self.assertEqual(before.project, after.project)
            self.assertEqual(before.created_at_utc, after.created_at_utc)
            self.assertEqual(before.ownership, after.ownership)

    def test_stale_expected_defaults_fail_without_overwriting_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._workspace(Path(temporary))
            update_workspace_defaults(
                root,
                reservation_minutes=180,
                placement="automatic",
                expected_reservation_minutes=120,
                expected_placement="automatic",
            )

            with self.assertRaisesRegex(WorkspaceError, "changed since they were read"):
                update_workspace_defaults(
                    root,
                    reservation_minutes=240,
                    placement="manual",
                    expected_reservation_minutes=120,
                    expected_placement="automatic",
                )

            current = load_workspace(root)
            self.assertEqual(180, current.reservation_minutes)
            self.assertEqual("automatic", current.placement)

    def test_workspace_model_validation_still_applies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._workspace(Path(temporary))
            with self.assertRaisesRegex(WorkspaceError, "reservation_minutes"):
                update_workspace_defaults(
                    root,
                    reservation_minutes=5,
                    placement="automatic",
                    expected_reservation_minutes=120,
                    expected_placement="automatic",
                )
            with self.assertRaisesRegex(WorkspaceError, "placement"):
                update_workspace_defaults(
                    root,
                    reservation_minutes=120,
                    placement="unsupported",
                    expected_reservation_minutes=120,
                    expected_placement="automatic",
                )


if __name__ == "__main__":
    unittest.main()
