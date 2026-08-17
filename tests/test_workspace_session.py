from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.workspace import (
    AccessRecord,
    Profile,
    WorkspaceError,
    WorkspaceRegistry,
    initialize_workspace,
    load_experiment_status,
    open_workspace_session,
    save_experiment_status,
)
from synthran.workspace.access import ProbeResult
from synthran.workspace.model import ExperimentStatus, format_utc
from synthran.workspace.store import save_access_record, save_profile


UTC = timezone.utc
NOW = datetime(2026, 8, 17, 19, 0, tzinfo=UTC)


def _fresh_access(provider: str, subject: str, scope: str) -> AccessRecord:
    return AccessRecord(
        provider=provider,
        subject=subject,
        scope=scope,
        verified_at_utc=format_utc(NOW - timedelta(hours=1)),
        refresh_after_utc=format_utc(NOW + timedelta(hours=11)),
        access_until_utc=(
            format_utc(NOW + timedelta(days=60)) if provider == "slices" else None
        ),
        identity_fingerprint=("SHA256:test" if provider == "r2lab" else None),
    )


class WorkspaceSessionTests(unittest.TestCase):
    def _workspace(self, root: Path, config_home: Path) -> tuple[str, str]:
        profile = Profile(
            name="controller",
            created_at_utc=format_utc(NOW),
            updated_at_utc=format_utc(NOW),
            slices_username="operator",
            r2lab_slice="slice_user",
            r2lab_identity="~/.ssh/id_r2lab",
            r2lab_identity_fingerprint="SHA256:test",
        )
        save_profile(
            profile,
            environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
        )
        initialize_workspace(
            root=root,
            profile="controller",
            project="research-project",
            now=NOW,
        )
        return profile.name, "research-project"

    def test_fresh_slow_access_is_reused_but_provider_experiment_is_rechecked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            config_home = base / "config"
            self._workspace(root, config_home)
            save_access_record(root, _fresh_access("slices", "operator", "research-project"))
            save_access_record(root, _fresh_access("r2lab", "slice_user", "faraday.inria.fr"))
            registry = WorkspaceRegistry(root)
            experiment = registry.create_experiment(
                profile="controller",
                project="research-project",
                slices_experiment="provider-exp-01",
                now=NOW,
            )

            def forbidden_runner(command: tuple[str, ...], timeout: int) -> ProbeResult:
                raise AssertionError(f"fresh access unexpectedly probed: {command}")

            experiment_calls: list[tuple[str, ...]] = []

            def experiment_runner(command: tuple[str, ...], timeout: int) -> ProbeResult:
                experiment_calls.append(command)
                return ProbeResult(0, "Experiment provider-exp-01 is active")

            with (
                patch(
                    "synthran.workspace.session.verify_profile_identity",
                    return_value="SHA256:test",
                ),
                patch(
                    "synthran.workspace.access.ssh_identity_fingerprint",
                    return_value="SHA256:test",
                ),
            ):
                session = open_workspace_session(
                    start=root,
                    environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
                    slices_runner=forbidden_runner,
                    r2lab_runner=forbidden_runner,
                    experiment_runner=experiment_runner,
                    now=NOW,
                )

            self.assertFalse(session.slices_access.refreshed)
            self.assertIsNotNone(session.r2lab_access)
            assert session.r2lab_access is not None
            self.assertFalse(session.r2lab_access.refreshed)
            self.assertEqual(session.experiment_id, experiment.experiment_id)
            self.assertEqual(
                experiment_calls,
                [("slices", "experiment", "show", "provider-exp-01")],
            )
            self.assertIsNotNone(session.provider_experiment)
            assert session.provider_experiment is not None
            self.assertEqual(session.provider_experiment.state, "active")
            persisted = load_experiment_status(root, experiment.experiment_id)
            self.assertEqual(persisted.provider_state, "active")
            self.assertEqual(persisted.state, "active")

    def test_stale_access_is_refreshed_and_provider_expiry_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            config_home = base / "config"
            self._workspace(root, config_home)
            stale = AccessRecord(
                provider="slices",
                subject="operator",
                scope="research-project",
                verified_at_utc=format_utc(NOW - timedelta(days=1)),
                refresh_after_utc=format_utc(NOW - timedelta(hours=12)),
                access_until_utc=format_utc(NOW + timedelta(days=30)),
            )
            save_access_record(root, stale)
            calls: list[tuple[str, ...]] = []

            def slices_runner(command: tuple[str, ...], timeout: int) -> ProbeResult:
                calls.append(command)
                if command == ("slices", "auth", "show"):
                    return ProbeResult(0, "authenticated")
                return ProbeResult(
                    0,
                    "Current project research-project; you are a member and it expires on 2026-10-22 23:59 UTC.",
                )

            with (
                patch(
                    "synthran.workspace.session.verify_profile_identity",
                    return_value="SHA256:test",
                ),
                patch(
                    "synthran.workspace.access.ssh_identity_fingerprint",
                    return_value="SHA256:test",
                ),
            ):
                session = open_workspace_session(
                    start=root,
                    environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
                    slices_runner=slices_runner,
                    r2lab_runner=lambda command, timeout: ProbeResult(0, ""),
                    now=NOW,
                )

            self.assertTrue(session.slices_access.refreshed)
            self.assertEqual(session.slices_access.record.access_until_utc, "2026-10-22T23:59:00Z")
            self.assertEqual(
                calls,
                [("slices", "auth", "show"), ("slices", "project", "show")],
            )

    def test_expired_provider_experiment_remains_saved_as_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            config_home = base / "config"
            self._workspace(root, config_home)
            save_access_record(root, _fresh_access("slices", "operator", "research-project"))
            save_access_record(root, _fresh_access("r2lab", "slice_user", "faraday.inria.fr"))
            registry = WorkspaceRegistry(root)
            experiment = registry.create_experiment(
                profile="controller",
                project="research-project",
                slices_experiment="provider-exp-02",
                now=NOW,
            )

            with (
                patch(
                    "synthran.workspace.session.verify_profile_identity",
                    return_value="SHA256:test",
                ),
                patch(
                    "synthran.workspace.access.ssh_identity_fingerprint",
                    return_value="SHA256:test",
                ),
            ):
                session = open_workspace_session(
                    start=root,
                    environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
                    slices_runner=lambda command, timeout: ProbeResult(0, ""),
                    r2lab_runner=lambda command, timeout: ProbeResult(0, ""),
                    experiment_runner=lambda command, timeout: ProbeResult(
                        2, "", "experiment expired"
                    ),
                    now=NOW + timedelta(hours=1),
                )

            self.assertIsNotNone(session.provider_experiment)
            assert session.provider_experiment is not None
            self.assertEqual(session.provider_experiment.state, "expired")
            self.assertTrue(
                (root / ".synthran" / "experiments" / experiment.experiment_id / "experiment.toml").is_file()
            )
            status = load_experiment_status(root, experiment.experiment_id)
            self.assertEqual(status.state, "expired")
            self.assertEqual(status.provider_state, "expired")

    def test_status_writer_refuses_orphan_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(root=root, profile="default", project="project", now=NOW)
            with self.assertRaises(WorkspaceError):
                save_experiment_status(
                    root,
                    ExperimentStatus(
                        experiment_id="sran-20260817-999",
                        state="configured",
                        updated_at_utc=format_utc(NOW),
                    ),
                )


if __name__ == "__main__":
    unittest.main()
