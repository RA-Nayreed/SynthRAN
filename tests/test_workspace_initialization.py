from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.workspace.access import ProbeResult
from synthran.workspace.initialization import (
    InitializationRequest,
    initialize_controller_workspace,
    persist_initialization,
    plan_initialization,
)
from synthran.workspace.model import WorkspaceError
from synthran.workspace.store import (
    load_access_record,
    load_profile,
    load_workspace,
    profile_path,
    workspace_directory,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 17, 19, 0, tzinfo=UTC)


def slices_runner(command: tuple[str, ...], timeout: int) -> ProbeResult:
    if command == ("slices", "auth", "show"):
        return ProbeResult(0, "authenticated")
    if command == ("slices", "project", "show"):
        return ProbeResult(
            0,
            "The current project is research-project, in which you are a member and which expires on 2026-10-22 23:59 UTC.",
        )
    raise AssertionError(command)


class InitializationTests(unittest.TestCase):
    def _request(self, root: Path, identity: Path | None = None) -> InitializationRequest:
        return InitializationRequest(
            root=root,
            profile_name="controller",
            slices_username="operator",
            project="research-project",
            r2lab_slice=("slice_user" if identity is not None else None),
            r2lab_identity=identity,
        )

    def test_success_verifies_first_then_persists_profile_workspace_and_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            config_home = base / "config"
            identity = base / "id_r2lab"
            identity.write_text("private fixture\n", encoding="utf-8")
            os.chmod(identity, 0o600)
            r2lab_calls: list[tuple[str, ...]] = []

            def r2lab_runner(command: tuple[str, ...], timeout: int) -> ProbeResult:
                r2lab_calls.append(command)
                self.assertFalse(workspace_directory(root).exists())
                self.assertFalse(
                    profile_path(
                        "controller",
                        environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
                    ).exists()
                )
                return ProbeResult(0, "")

            with patch(
                "synthran.workspace.initialization.ssh_identity_fingerprint",
                return_value="SHA256:fixture",
            ), patch(
                "synthran.workspace.access.ssh_identity_fingerprint",
                return_value="SHA256:fixture",
            ):
                result = initialize_controller_workspace(
                    self._request(root, identity),
                    environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
                    slices_runner=slices_runner,
                    r2lab_runner=r2lab_runner,
                    now=NOW,
                )

            self.assertTrue(result.profile_created)
            self.assertEqual(result.profile.r2lab_identity_fingerprint, "SHA256:fixture")
            self.assertEqual(
                load_profile(
                    "controller",
                    environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
                ),
                result.profile,
            )
            self.assertEqual(load_workspace(root), result.workspace)
            self.assertEqual(load_access_record(root, "slices"), result.slices_access)
            self.assertEqual(load_access_record(root, "r2lab"), result.r2lab_access)
            self.assertEqual(
                result.slices_access.access_until_utc,
                "2026-10-22T23:59:00Z",
            )
            self.assertEqual(len(r2lab_calls), 1)
            command = r2lab_calls[0]
            self.assertIn("IdentitiesOnly=yes", command)
            self.assertEqual(command[command.index("-i") + 1], str(identity.resolve()))
            profile_text = profile_path(
                "controller",
                environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
            ).read_text(encoding="utf-8")
            self.assertNotIn("private fixture", profile_text)

    def test_failed_remote_verification_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            config_home = base / "config"

            def failed_slices(command: tuple[str, ...], timeout: int) -> ProbeResult:
                return ProbeResult(2, "", "not authenticated")

            with self.assertRaises(WorkspaceError):
                initialize_controller_workspace(
                    self._request(root),
                    environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
                    slices_runner=failed_slices,
                    now=NOW,
                )
            self.assertFalse(workspace_directory(root).exists())
            self.assertFalse(
                profile_path(
                    "controller",
                    environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
                ).exists()
            )

    def test_r2lab_failure_does_not_leave_slices_only_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            config_home = base / "config"
            identity = base / "id_r2lab"
            identity.write_text("fixture\n", encoding="utf-8")
            os.chmod(identity, 0o600)

            with patch(
                "synthran.workspace.initialization.ssh_identity_fingerprint",
                return_value="SHA256:fixture",
            ), patch(
                "synthran.workspace.access.ssh_identity_fingerprint",
                return_value="SHA256:fixture",
            ):
                with self.assertRaises(WorkspaceError):
                    initialize_controller_workspace(
                        self._request(root, identity),
                        environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
                        slices_runner=slices_runner,
                        r2lab_runner=lambda command, timeout: ProbeResult(
                            255, "", "denied"
                        ),
                        now=NOW,
                    )
            self.assertFalse(workspace_directory(root).exists())
            self.assertFalse(
                profile_path(
                    "controller",
                    environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
                ).exists()
            )

    def test_existing_profile_requires_explicit_reuse_without_reentering_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first_root = base / "first"
            first_root.mkdir()
            second_root = base / "second"
            second_root.mkdir()
            config_home = base / "config"
            identity = base / "id_r2lab"
            identity.write_text("fixture\n", encoding="utf-8")
            os.chmod(identity, 0o600)
            environment = {"SYNTHRAN_CONFIG_HOME": str(config_home)}

            with patch(
                "synthran.workspace.initialization.ssh_identity_fingerprint",
                return_value="SHA256:fixture",
            ), patch(
                "synthran.workspace.access.ssh_identity_fingerprint",
                return_value="SHA256:fixture",
            ):
                initialize_controller_workspace(
                    self._request(first_root, identity),
                    environment=environment,
                    slices_runner=slices_runner,
                    r2lab_runner=lambda command, timeout: ProbeResult(0, ""),
                    now=NOW,
                )
                with self.assertRaises(WorkspaceError):
                    plan_initialization(
                        self._request(second_root, identity),
                        environment=environment,
                        slices_runner=slices_runner,
                        r2lab_runner=lambda command, timeout: ProbeResult(0, ""),
                        now=NOW,
                    )
                reused = InitializationRequest(
                    root=second_root,
                    profile_name="controller",
                    project="research-project",
                    reuse_profile=True,
                )
                result = initialize_controller_workspace(
                    reused,
                    environment=environment,
                    slices_runner=slices_runner,
                    r2lab_runner=lambda command, timeout: ProbeResult(0, ""),
                    now=NOW,
                )
            self.assertFalse(result.profile_created)
            self.assertEqual(result.workspace.profile, "controller")
            self.assertEqual(result.profile.r2lab_identity, str(identity.resolve()))

    def test_reused_profile_rejects_identity_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(WorkspaceError):
                InitializationRequest(
                    root=root,
                    profile_name="controller",
                    project="research-project",
                    slices_username="other",
                    reuse_profile=True,
                )

    def test_persist_detects_local_state_race(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            config_home = base / "config"
            environment = {"SYNTHRAN_CONFIG_HOME": str(config_home)}
            plan = plan_initialization(
                self._request(root),
                environment=environment,
                slices_runner=slices_runner,
                now=NOW,
            )
            workspace_directory(root).mkdir()
            with self.assertRaises(WorkspaceError):
                persist_initialization(plan, environment=environment, now=NOW)
            self.assertFalse(
                profile_path("controller", environment=environment).exists()
            )


if __name__ == "__main__":
    unittest.main()
