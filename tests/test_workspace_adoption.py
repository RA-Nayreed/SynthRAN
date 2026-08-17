from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.workspace.access import ProbeResult
from synthran.workspace.initialization import (
    InitializationRequest,
    initialize_controller_workspace,
)
from synthran.workspace.model import WorkspaceError
from synthran.workspace.store import (
    load_access_record,
    load_workspace,
    profile_path,
    workspace_directory,
    workspace_file,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)


def slices_runner(command: tuple[str, ...], timeout: int) -> ProbeResult:
    if command == ("slices", "auth", "show"):
        return ProbeResult(0, "authenticated")
    if command == ("slices", "project", "show"):
        return ProbeResult(
            0,
            "The current project is post5g-beta, in which you are a member and which expires on 2026-10-22 23:59 UTC.",
        )
    raise AssertionError(command)


def request(root: Path) -> InitializationRequest:
    return InitializationRequest(
        root=root,
        profile_name="controller",
        slices_username="operator",
        project="post5g-beta",
    )


class WorkspaceAdoptionTests(unittest.TestCase):
    def test_existing_legacy_artifacts_are_preserved_during_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            legacy = workspace_directory(root)
            (legacy / "runs" / "network-acceptance-20260817-04").mkdir(parents=True)
            (legacy / "experiments" / "iot-acceptance-20260817-06").mkdir(parents=True)
            evidence = legacy / "runs" / "network-acceptance-20260817-04" / "network-evidence.json"
            evidence.write_text("legacy-evidence\n", encoding="utf-8")
            telemetry = legacy / "experiments" / "iot-acceptance-20260817-06" / "telemetry.jsonl"
            telemetry.write_text("legacy-telemetry\n", encoding="utf-8")
            environment = {"SYNTHRAN_CONFIG_HOME": str(base / "config")}

            result = initialize_controller_workspace(
                request(root),
                environment=environment,
                slices_runner=slices_runner,
                now=NOW,
            )

            self.assertTrue(workspace_file(root).is_file())
            self.assertEqual(load_workspace(root), result.workspace)
            self.assertEqual(load_access_record(root, "slices"), result.slices_access)
            self.assertEqual(evidence.read_text(encoding="utf-8"), "legacy-evidence\n")
            self.assertEqual(telemetry.read_text(encoding="utf-8"), "legacy-telemetry\n")

    def test_failed_persistence_never_removes_preexisting_legacy_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            legacy = workspace_directory(root)
            (legacy / "preparations" / "network-01").mkdir(parents=True)
            marker = legacy / "preparations" / "network-01" / "hosts.ini"
            marker.write_text("legacy inventory\n", encoding="utf-8")
            environment = {"SYNTHRAN_CONFIG_HOME": str(base / "config")}

            with patch(
                "synthran.workspace.initialization.save_access_record",
                side_effect=WorkspaceError("fixture persistence failure"),
            ):
                with self.assertRaises(WorkspaceError):
                    initialize_controller_workspace(
                        request(root),
                        environment=environment,
                        slices_runner=slices_runner,
                        now=NOW,
                    )

            self.assertTrue(marker.is_file())
            self.assertEqual(marker.read_text(encoding="utf-8"), "legacy inventory\n")
            self.assertFalse(workspace_file(root).exists())
            self.assertFalse(profile_path("controller", environment=environment).exists())

    def test_partial_new_workspace_state_is_not_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            legacy = workspace_directory(root)
            legacy.mkdir()
            (legacy / "registry.sqlite3").write_bytes(b"partial")
            called = False

            def runner(command: tuple[str, ...], timeout: int) -> ProbeResult:
                nonlocal called
                called = True
                return slices_runner(command, timeout)

            with self.assertRaises(WorkspaceError):
                initialize_controller_workspace(
                    request(root),
                    environment={"SYNTHRAN_CONFIG_HOME": str(base / "config")},
                    slices_runner=runner,
                    now=NOW,
                )
            self.assertFalse(called)

    def test_new_format_experiment_without_workspace_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            experiment = workspace_directory(root) / "experiments" / "sran-20260818-001"
            experiment.mkdir(parents=True)

            with self.assertRaises(WorkspaceError):
                initialize_controller_workspace(
                    request(root),
                    environment={"SYNTHRAN_CONFIG_HOME": str(base / "config")},
                    slices_runner=slices_runner,
                    now=NOW,
                )


if __name__ == "__main__":
    unittest.main()
