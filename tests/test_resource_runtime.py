from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.dependencies import load_lock
from synthran.live_preflight import CommandResult
from synthran.resource_runtime import (
    PREPARATION_SCHEMA,
    ResourcePreparationError,
    build_preparation_inventory,
    build_resource_preparation_plan,
    execute_resource_preparation,
)
from synthran.slices_controller import (
    SlicesControllerReport,
    dependency_lock_sha256,
    fingerprint,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


class PreparationRunner:
    def __init__(
        self,
        *,
        allocation_records=None,
        reservation_records=None,
        fail_stage: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.environments: list[dict[str, str] | None] = []
        self.allocation_records = (
            [] if allocation_records is None else allocation_records
        )
        self.reservation_records = (
            [
                {
                    "id": 7000000001,
                    "owner": "operator",
                    "nodes": ["sopnode-f2", "sopnode-f3"],
                    "start_date": "2026-08-12T11:00:00Z",
                    "end_date": "2026-08-12T14:00:00Z",
                }
            ]
            if reservation_records is None
            else reservation_records
        )
        self.fail_stage = fail_stage
        self.reservation_created = False
        self.checkout: Path | None = None
        self.commit: str | None = None

    def __call__(self, command, _cwd, environment, _timeout):
        argv = tuple(command)
        self.calls.append(argv)
        self.environments.append(environment)
        if self.fail_stage and self.fail_stage in " ".join(argv):
            return CommandResult(2, "operator 7000000001 192.168.2.7")
        if argv[:2] == ("git", "-C") and "worktree" in argv:
            self.checkout = Path(argv[2])
            self.commit = argv[-1]
            Path(argv[-2]).mkdir(parents=True)
            return CommandResult(0, "worktree created")
        if argv == ("git", "rev-parse", "HEAD"):
            return CommandResult(0, f"{self.commit}\n")
        if argv == ("pos", "allocations", "list", "--json"):
            return CommandResult(0, json.dumps(self.allocation_records))
        if argv[:3] == ("pos", "calendar", "create"):
            self.reservation_created = True
            return CommandResult(0, "7000000001\n")
        if argv[:3] == ("pos", "allocations", "allocate"):
            # Real POS 2.5.35 does not reliably return the allocation ID
            # on stdout. The authoritative ID is discovered with
            # `pos allocations show` after creation.
            return CommandResult(0, "")
        if argv == (
            "pos",
            "calendar",
            "list",
            "--filter",
            "owner=operator",
            "--json",
        ):
            records = self.reservation_records if self.reservation_created else []
            return CommandResult(0, json.dumps(records))
        if argv[:3] == ("pos", "allocations", "show"):
            return CommandResult(
                0,
                json.dumps({"id": "allocation-pair", "owner": "operator"}),
            )
        return CommandResult(0, "ok")


class ResourcePreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        self.plan = build_resource_preparation_plan(
            lock=self.lock,
            core_node="sopnode-f2",
            ran_node="sopnode-f3",
            duration_minutes=120,
            run_id="prepare-001",
        )
        self.ready_plan = replace(
            self.plan,
            bootstrap_status="ready",
            bootstrap_reason="test-only reviewed bootstrap",
        )
        self.controller = SlicesControllerReport(
            dependency_lock_sha256=dependency_lock_sha256(self.lock),
            project_fingerprint=fingerprint("project-test"),
            experiment_fingerprint=fingerprint("experiment-test"),
            python_version="3.12.13",
            ansible_version="2.20.5",
            pos_version="2.5.35",
            slices_cli_version="1.4.0",
        )

    def test_inventory_uses_locked_upstream_node_mappings(self) -> None:
        text, inventory = build_preparation_inventory(
            core_node="sopnode-f2",
            ran_node="sopnode-f3",
            source=Path("hosts.ini"),
        )
        self.assertIn(
            "sopnode-f2 ansible_user=root nic_interface=ens2f1 "
            "ip=172.28.2.77 storage=sda1",
            text,
        )
        self.assertIn(
            "sopnode-f3 ansible_user=root nic_interface=ens15f1 "
            "ip=172.28.2.95 storage=sdb2 boot_mode=live",
            text,
        )
        self.assertEqual("sopnode-f2", inventory.core_node.name)
        self.assertEqual("sopnode-f3", inventory.ran_node.name)

    def test_rejects_unsupported_or_colocated_nodes(self) -> None:
        with self.assertRaisesRegex(ResourcePreparationError, "unsupported"):
            build_preparation_inventory(
                core_node="unknown",
                ran_node="sopnode-f3",
                source=Path("hosts.ini"),
            )
        with self.assertRaisesRegex(ResourcePreparationError, "separate"):
            build_preparation_inventory(
                core_node="sopnode-f2",
                ran_node="sopnode-f2",
                source=Path("hosts.ini"),
            )

    def test_plan_uses_one_shared_allocation_and_never_deploy_sh(self) -> None:
        rendered = self.plan.render()
        self.assertEqual("ready", self.plan.bootstrap_status)
        self.assertIn(
            "pos allocations allocate sopnode-f2 sopnode-f3",
            rendered,
        )
        self.assertIn("pos calendar create -d 120 -s now", rendered)
        self.assertNotIn("allocations free", rendered)
        self.assertNotIn("deploy.sh", rendered)
        self.assertIn("stops before Open5GS or srsRAN deployment", rendered)

    def test_live_preparation_is_blocked_before_any_provider_call(self) -> None:
        blocked_plan = replace(
            self.plan,
            bootstrap_status="blocked",
            bootstrap_reason="test-only blocked bootstrap",
        )
        runner = PreparationRunner()
        with self.assertRaisesRegex(ResourcePreparationError, "blocked by the dependency lock"):
            execute_resource_preparation(
                plan=blocked_plan,
                lock=self.lock,
                dependency_root=Path("unused"),
                owner="operator",
                slices_project="project-test",
                slices_experiment="experiment-test",
                runner=runner,
            )
        self.assertEqual([], runner.calls)

    def test_success_writes_private_authority_and_sanitized_manifest(self) -> None:
        runner = PreparationRunner()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "checkout"
            checkout.mkdir()
            with (
                patch(
                    "synthran.resource_runtime.validate_fiveg_checkout",
                    return_value=checkout,
                ),
                patch("synthran.resource_runtime.shutil.which", return_value="/tool"),
                patch(
                    "synthran.resource_runtime.verify_slices_controller",
                    return_value=self.controller,
                ),
            ):
                result = execute_resource_preparation(
                    plan=self.ready_plan,
                    lock=self.lock,
                    dependency_root=root / "deps",
                    owner="operator",
                    slices_project="project-test",
                    slices_experiment="experiment-test",
                    run_root=root / "preparations",
                    repository_root=REPOSITORY_ROOT,
                    runner=runner,
                    now=NOW,
                )

            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            rendered_manifest = json.dumps(manifest)
            self.assertEqual(PREPARATION_SCHEMA, manifest["schema"])
            self.assertEqual("prepared", manifest["status"])
            self.assertEqual("create", manifest["allocation_action"])
            self.assertEqual(
                self.controller.dependency_lock_sha256,
                manifest["dependency_lock_sha256"],
            )
            self.assertEqual(self.controller.to_dict(), manifest["slices_controller"])
            self.assertNotIn("dependency_lock_sha256", manifest["authority"])
            for private in ("operator", "7000000001", "allocation-pair"):
                self.assertNotIn(private, rendered_manifest)
                self.assertNotIn(
                    private,
                    result.log_path.read_text(encoding="utf-8"),
                )
            authority = result.authority_path.read_text(encoding="utf-8")
            self.assertIn("export SYNTHRAN_OWNER=operator", authority)
            self.assertIn("export SYNTHRAN_RESERVATION_ID=7000000001", authority)
            self.assertIn("export SYNTHRAN_ALLOCATION_ID=allocation-pair", authority)
            self.assertIn("export SYNTHRAN_KNOWN_HOSTS=", authority)
            self.assertIn("known_hosts", authority)
            if os.name != "nt":
                self.assertEqual(0o600, result.authority_path.stat().st_mode & 0o777)

            allocate_calls = [
                call for call in runner.calls if call[:3] == ("pos", "allocations", "allocate")
            ]
            self.assertEqual(
                [("pos", "allocations", "allocate", "sopnode-f2", "sopnode-f3")],
                allocate_calls,
            )
            self.assertFalse(any("free" in call for call in runner.calls))
            collection_calls = [
                call
                for call in runner.calls
                if call[:3] == ("ansible-galaxy", "collection", "install")
            ]
            self.assertEqual(1, len(collection_calls))
            self.assertTrue(
                any(
                    part.endswith("preparation-requirements.yml")
                    for part in collection_calls[0]
                )
            )
            live_playbooks = [
                call
                for call in runner.calls
                if call and call[0] == "ansible-playbook" and "--syntax-check" not in call
            ]
            self.assertTrue(
                any("synthran_prepare_only=true" in call for call in live_playbooks)
            )
            self.assertTrue(
                any(
                    environment is not None
                    and environment["ANSIBLE_HOST_KEY_CHECKING"] == "True"
                    and "StrictHostKeyChecking=accept-new"
                    in environment["ANSIBLE_SSH_ARGS"]
                    and "UserKnownHostsFile=" in environment["ANSIBLE_SSH_ARGS"]
                    for environment in runner.environments
                )
            )

    def test_conflicting_allocation_fails_before_pos_mutation(self) -> None:
        runner = PreparationRunner(
            allocation_records=[
                {
                    "id": "foreign",
                    "owner": "someone-else",
                    "nodes": ["sopnode-f2", "sopnode-f3"],
                }
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "checkout"
            checkout.mkdir()
            with (
                patch(
                    "synthran.resource_runtime.validate_fiveg_checkout",
                    return_value=checkout,
                ),
                patch("synthran.resource_runtime.shutil.which", return_value="/tool"),
                patch(
                    "synthran.resource_runtime.verify_slices_controller",
                    return_value=self.controller,
                ),
                self.assertRaisesRegex(ResourcePreparationError, "another operator"),
            ):
                execute_resource_preparation(
                    plan=self.ready_plan,
                    lock=self.lock,
                    dependency_root=root / "deps",
                    owner="operator",
                    slices_project="project-test",
                    slices_experiment="experiment-test",
                    run_root=root / "preparations",
                    repository_root=REPOSITORY_ROOT,
                    runner=runner,
                    now=NOW,
                )
            self.assertFalse(
                any(
                    call[:3] == ("pos", "calendar", "create")
                    or call[:3] == ("pos", "allocations", "allocate")
                    for call in runner.calls
                )
            )

    def test_reservation_failure_is_terminal_and_keeps_artifacts(self) -> None:
        runner = PreparationRunner(reservation_records=[])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "checkout"
            checkout.mkdir()
            with (
                patch(
                    "synthran.resource_runtime.validate_fiveg_checkout",
                    return_value=checkout,
                ),
                patch("synthran.resource_runtime.shutil.which", return_value="/tool"),
                patch(
                    "synthran.resource_runtime.verify_slices_controller",
                    return_value=self.controller,
                ),
                self.assertRaisesRegex(
                    ResourcePreparationError,
                    "supplied reservation could not be verified",
                ),
            ):
                execute_resource_preparation(
                    plan=self.ready_plan,
                    lock=self.lock,
                    dependency_root=root / "deps",
                    owner="operator",
                    slices_project="project-test",
                    slices_experiment="experiment-test",
                    run_root=root / "preparations",
                    repository_root=REPOSITORY_ROOT,
                    runner=runner,
                    now=NOW,
                )
            run_directory = root / "preparations" / "prepare-001"
            manifest = json.loads(
                (run_directory / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual("failed", manifest["status"])
            self.assertEqual(
                "reservation-verification",
                manifest["failure_stage"],
            )
            self.assertTrue((run_directory / "preparation.log").is_file())
            self.assertFalse(
                any(
                    call[:3] == ("pos", "allocations", "allocate")
                    for call in runner.calls
                )
            )

    def test_preparation_progress_stream_reports_stages(self) -> None:
        from io import StringIO

        runner = PreparationRunner()
        progress = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "checkout"
            checkout.mkdir()
            with (
                patch(
                    "synthran.resource_runtime.validate_fiveg_checkout",
                    return_value=checkout,
                ),
                patch("synthran.resource_runtime.shutil.which", return_value="/tool"),
                patch(
                    "synthran.resource_runtime.verify_slices_controller",
                    return_value=self.controller,
                ),
            ):
                execute_resource_preparation(
                    plan=self.ready_plan,
                    lock=self.lock,
                    dependency_root=root / "deps",
                    owner="operator",
                    slices_project="project-test",
                    slices_experiment="experiment-test",
                    run_root=root / "preparations",
                    repository_root=REPOSITORY_ROOT,
                    runner=runner,
                    now=NOW,
                    progress=progress,
                )

            text = progress.getvalue()
            self.assertIn("[synthran]", text)
            self.assertIn("preparation started: run=prepare-001", text)
            self.assertIn("controller-preflight: running...", text)
            self.assertIn("controller-preflight: OK", text)
            self.assertIn("isolated-worktree: running...", text)
            self.assertIn("isolated-worktree: OK", text)
            self.assertIn("resource preparation: COMPLETE", text)


if __name__ == "__main__":
    unittest.main()
