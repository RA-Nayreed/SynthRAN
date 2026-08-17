from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.workspace import (
    AccessRecord,
    WorkspaceError,
    WorkspaceRegistry,
    create_or_update_profile,
    initialize_workspace,
    load_access_record,
    load_active_experiment_id,
    load_experiment_record,
    load_profile,
    load_workspace,
    verify_r2lab_gateway_access,
    verify_slices_project_access,
)
from synthran.workspace.access import ProbeResult, ensure_r2lab_gateway_access
from synthran.workspace.records import load_operation_record, load_run_record
from synthran.workspace.store import profile_path, save_access_record


UTC = timezone.utc
NOW = datetime(2026, 8, 17, 19, 0, tzinfo=UTC)


class WorkspaceTests(unittest.TestCase):
    def test_profile_keeps_only_identity_reference_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "id_test"
            identity.write_text("private material must never be copied\n", encoding="utf-8")
            os.chmod(identity, 0o600)
            environment = {"SYNTHRAN_CONFIG_HOME": str(root / "config")}
            with patch(
                "synthran.workspace.store.ssh_identity_fingerprint",
                return_value="SHA256:testfingerprint",
            ):
                profile = create_or_update_profile(
                    name="duckburg",
                    slices_username="operator",
                    r2lab_slice="slice_user",
                    r2lab_identity=identity,
                    environment=environment,
                    now=NOW,
                )
            saved = profile_path("duckburg", environment=environment)
            text = saved.read_text(encoding="utf-8")
            self.assertEqual(profile.r2lab_identity_fingerprint, "SHA256:testfingerprint")
            self.assertIn(str(identity), text)
            self.assertNotIn("private material", text)
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            loaded = load_profile("duckburg", environment=environment)
            self.assertEqual(loaded, profile)

    def test_profile_update_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            environment = {"SYNTHRAN_CONFIG_HOME": str(Path(temporary) / "config")}
            create_or_update_profile(
                name="default",
                slices_username="operator",
                r2lab_slice=None,
                r2lab_identity=None,
                environment=environment,
                now=NOW,
            )
            with self.assertRaises(WorkspaceError):
                create_or_update_profile(
                    name="default",
                    slices_username="other",
                    r2lab_slice=None,
                    r2lab_identity=None,
                    environment=environment,
                    now=NOW,
                )

    def test_workspace_and_experiment_folders_are_durable_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = initialize_workspace(
                root=root,
                profile="duckburg",
                project="research-project",
                now=NOW,
            )
            self.assertEqual(load_workspace(root), workspace)
            registry = WorkspaceRegistry(root)
            first = registry.create_experiment(
                profile="duckburg",
                project="research-project",
                label="first network",
                slices_experiment="provider-exp-01",
                network_intent="iot-to-5g",
                radio_mode="automatic",
                now=NOW,
            )
            second = registry.create_experiment(
                profile="duckburg",
                project="research-project",
                now=NOW + timedelta(minutes=1),
            )
            self.assertEqual(first.experiment_id, "sran-20260817-001")
            self.assertEqual(second.experiment_id, "sran-20260817-002")
            self.assertEqual(load_active_experiment_id(root), second.experiment_id)
            loaded = load_experiment_record(root, first.experiment_id)
            self.assertEqual(loaded, first)
            directory = root / ".synthran" / "experiments" / first.experiment_id
            for expected in (
                "experiment.toml",
                "status.json",
                "providers",
                "operations",
                "runs",
                "evidence",
                "datasets",
            ):
                self.assertTrue((directory / expected).exists(), expected)

    def test_rebuild_restores_all_non_reuse_counters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(root=root, profile="default", project="project", now=NOW)
            registry = WorkspaceRegistry(root)
            first = registry.create_experiment(
                profile="default", project="project", now=NOW
            )
            second = registry.create_experiment(
                profile="default", project="project", now=NOW + timedelta(minutes=1)
            )
            run1 = registry.issue_run_id(
                experiment_id=first.experiment_id,
                label="baseline",
                now=NOW + timedelta(minutes=2),
            )
            run2 = registry.issue_run_id(
                experiment_id=first.experiment_id,
                label="load050",
                now=NOW + timedelta(minutes=3),
            )
            op1 = registry.issue_operation_id(
                kind="verify",
                experiment_id=first.experiment_id,
                now=NOW + timedelta(minutes=4),
            )
            op2 = registry.issue_operation_id(
                kind="collect", now=NOW + timedelta(minutes=5)
            )
            self.assertEqual(run1, "run-001-baseline")
            self.assertEqual(run2, "run-002-load050")
            self.assertEqual(op1, "op-000001")
            self.assertEqual(op2, "op-000002")
            self.assertEqual(
                load_run_record(root, first.experiment_id, run2).run_id,
                run2,
            )
            self.assertEqual(load_operation_record(root, op1).kind, "verify")

            database = root / ".synthran" / "registry.sqlite3"
            wal = root / ".synthran" / "registry.sqlite3-wal"
            shm = root / ".synthran" / "registry.sqlite3-shm"
            database.unlink()
            if wal.exists():
                wal.unlink()
            if shm.exists():
                shm.unlink()

            rebuilt = WorkspaceRegistry(root)
            self.assertEqual(rebuilt.rebuild_from_experiment_folders(), 2)
            third = rebuilt.create_experiment(
                profile="default", project="project", now=NOW + timedelta(minutes=6)
            )
            run3 = rebuilt.issue_run_id(
                experiment_id=first.experiment_id,
                label="load075",
                now=NOW + timedelta(minutes=7),
            )
            op3 = rebuilt.issue_operation_id(
                kind="analyze", now=NOW + timedelta(minutes=8)
            )
            self.assertEqual(second.experiment_id, "sran-20260817-002")
            self.assertEqual(third.experiment_id, "sran-20260817-003")
            self.assertEqual(run3, "run-003-load075")
            self.assertEqual(op3, "op-000003")

    def test_incomplete_run_and_operation_directories_still_consume_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(root=root, profile="default", project="project", now=NOW)
            registry = WorkspaceRegistry(root)
            experiment = registry.create_experiment(
                profile="default", project="project", now=NOW
            )
            runs = root / ".synthran" / "experiments" / experiment.experiment_id / "runs"
            (runs / "run-007-aborted").mkdir()
            operations = root / ".synthran" / "operations"
            (operations / "op-000009").mkdir()

            database = root / ".synthran" / "registry.sqlite3"
            database.unlink()
            rebuilt = WorkspaceRegistry(root)
            rebuilt.rebuild_from_experiment_folders()
            self.assertEqual(
                rebuilt.issue_run_id(
                    experiment_id=experiment.experiment_id,
                    label="retry",
                    now=NOW + timedelta(minutes=1),
                ),
                "run-008-retry",
            )
            self.assertEqual(
                rebuilt.issue_operation_id(
                    kind="retry", now=NOW + timedelta(minutes=2)
                ),
                "op-000010",
            )

    def test_run_and_operation_ids_have_independent_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(root=root, profile="default", project="project", now=NOW)
            registry = WorkspaceRegistry(root)
            experiment = registry.create_experiment(
                profile="default", project="project", now=NOW
            )
            run1 = registry.issue_run_id(
                experiment_id=experiment.experiment_id,
                label="baseline",
                now=NOW,
            )
            run2 = registry.issue_run_id(
                experiment_id=experiment.experiment_id,
                label="load050",
                now=NOW,
            )
            op1 = registry.issue_operation_id(
                kind="verify", experiment_id=experiment.experiment_id, now=NOW
            )
            op2 = registry.issue_operation_id(kind="collect", now=NOW)
            self.assertEqual(run1, "run-001-baseline")
            self.assertEqual(run2, "run-002-load050")
            self.assertEqual(op1, "op-000001")
            self.assertEqual(op2, "op-000002")

    def test_access_cache_has_refresh_and_provider_expiry_boundaries(self) -> None:
        record = AccessRecord(
            provider="slices",
            subject="operator",
            scope="project",
            verified_at_utc="2026-08-17T19:00:00Z",
            refresh_after_utc="2026-08-18T07:00:00Z",
            access_until_utc="2026-10-22T23:59:00Z",
        )
        self.assertTrue(record.is_fresh(datetime(2026, 8, 18, 6, 59, tzinfo=UTC)))
        self.assertFalse(record.is_fresh(datetime(2026, 8, 18, 7, 0, tzinfo=UTC)))
        self.assertTrue(record.is_expired(datetime(2026, 10, 23, 0, 0, tzinfo=UTC)))

    def test_slices_access_probe_persists_expiry_and_refreshes_before_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(root=root, profile="default", project="project", now=NOW)

            def runner(command: tuple[str, ...], timeout: int) -> ProbeResult:
                self.assertEqual(timeout, 30)
                if command[:3] == ("slices", "auth", "show"):
                    return ProbeResult(0, "authenticated")
                return ProbeResult(
                    0,
                    "Current project project; you are a member and it expires on 2026-08-17 22:00 UTC.",
                )

            record = verify_slices_project_access(
                workspace_root=root,
                username="operator",
                project="project",
                runner=runner,
                now=NOW,
            )
            self.assertEqual(record.access_until_utc, "2026-08-17T22:00:00Z")
            self.assertEqual(record.refresh_after_utc, "2026-08-17T22:00:00Z")
            self.assertEqual(load_access_record(root, "slices"), record)

    def test_r2lab_access_probe_uses_exact_profile_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(root=root, profile="default", project="project", now=NOW)
            identity = root / "id_r2lab"
            identity.write_text("not read by fake runner", encoding="utf-8")
            os.chmod(identity, 0o600)
            seen: list[tuple[str, ...]] = []

            def runner(command: tuple[str, ...], timeout: int) -> ProbeResult:
                seen.append(command)
                return ProbeResult(0, "")

            with patch(
                "synthran.workspace.access.ssh_identity_fingerprint",
                return_value="SHA256:identityone",
            ):
                record = verify_r2lab_gateway_access(
                    workspace_root=root,
                    slice_name="slice_user",
                    identity_reference=str(identity),
                    runner=runner,
                    now=NOW,
                )
            command = seen[0]
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn("IdentitiesOnly=yes", command)
            self.assertEqual(command[command.index("-i") + 1], str(identity.resolve()))
            self.assertEqual(record.identity_fingerprint, "SHA256:identityone")
            self.assertTrue(record.is_fresh(NOW + timedelta(hours=1)))

    def test_r2lab_cache_is_invalidated_when_identity_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(root=root, profile="default", project="project", now=NOW)
            identity = root / "id_r2lab"
            identity.write_text("not read by fake runner", encoding="utf-8")
            os.chmod(identity, 0o600)
            save_access_record(
                root,
                AccessRecord(
                    provider="r2lab",
                    subject="slice_user",
                    scope="faraday.inria.fr",
                    verified_at_utc="2026-08-17T18:00:00Z",
                    refresh_after_utc="2026-08-18T06:00:00Z",
                    identity_fingerprint="SHA256:oldidentity",
                ),
            )
            seen: list[tuple[str, ...]] = []

            def runner(command: tuple[str, ...], timeout: int) -> ProbeResult:
                seen.append(command)
                return ProbeResult(0, "")

            with patch(
                "synthran.workspace.access.ssh_identity_fingerprint",
                return_value="SHA256:newidentity",
            ):
                record, refreshed = ensure_r2lab_gateway_access(
                    workspace_root=root,
                    slice_name="slice_user",
                    identity_reference=str(identity),
                    runner=runner,
                    now=NOW,
                )
            self.assertTrue(refreshed)
            self.assertEqual(record.identity_fingerprint, "SHA256:newidentity")
            self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
