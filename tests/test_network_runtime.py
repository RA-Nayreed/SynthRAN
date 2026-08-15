from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import os
from synthran.dependencies import load_lock
from synthran.fiveg_ansible import build_network_plan, load_inventory
from synthran.live_preflight import CommandResult
from synthran.network_runtime import (
    DEPLOYMENT_SCHEMA,
    NETWORK_EVIDENCE_SCHEMA,
    NetworkRuntimeError,
    execute_network_deployment,
    golden_path_image_variables,
    sanitize_deployment_text,
    validate_run_id,
    verify_network_path,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "inventory_open5gs_srsran_rfsim.ini"
NOW = datetime(2026, 8, 12, 14, 0, tzinfo=timezone.utc)


class VerificationRunner:
    def __init__(self, images: dict[str, str], run_id: str = "network-proof") -> None:
        self.images = images
        self.run_id = run_id
        self.calls: list[tuple[str, ...]] = []

    def _pod(self, name: str, container: str, reference: str) -> dict[str, object]:
        digest = reference.rsplit("@", 1)[1]
        statuses = [
            {
                "name": container,
                "imageID": f"docker-pullable://locked@{digest}",
                "ready": True,
                "state": {"running": {"startedAt": "2026-08-12T13:59:00Z"}},
            }
        ]
        if container == "gnb":
            helper_digest = self.images["busybox_1_36"].rsplit("@", 1)[1]
            statuses.append(
                {
                    "name": "gnb-logs",
                    "imageID": f"docker-pullable://locked@{helper_digest}",
                    "ready": True,
                    "state": {"running": {"startedAt": "2026-08-12T13:59:00Z"}},
                }
            )
        return {
            "metadata": {
                "name": name,
                "labels": {"synthran.run/id": self.run_id},
            },
            "status": {
                "phase": "Running",
                "conditions": [{"type": "Ready", "status": "True"}],
                "containerStatuses": statuses,
            },
        }

    def __call__(self, command: tuple[str, ...] | list[str], timeout: int) -> CommandResult:
        argv = tuple(command)
        self.calls.append(argv)
        if timeout <= 0:
            raise AssertionError("timeout must be positive")
        remote = argv[-1]
        if "app=srsran,component=gnb" in remote:
            payload = self._pod("gnb-pod", "gnb", self.images["srsran_gnb"])
            return CommandResult(0, json.dumps({"items": [payload]}))
        if "app=srsran,component=ue" in remote:
            payload = self._pod("ue-pod", "ue", self.images["srsran_ue"])
            return CommandResult(0, json.dumps({"items": [payload]}))
        if "app=open5gs,nf=upf,name=upf1" in remote:
            payload = self._pod("upf-pod", "upf", self.images["open5gs"])
            return CommandResult(0, json.dumps({"items": [payload]}))
        if "gnb-pod -c gnb-logs" in remote:
            return CommandResult(0, "")
        if "ip -j address show dev tun_srsue1" in remote:
            return CommandResult(
                0,
                json.dumps(
                    [
                        {
                            "ifname": "tun_srsue1",
                            "flags": ["POINTOPOINT", "UP", "LOWER_UP"],
                            "addr_info": [
                                {"family": "inet", "local": "12.1.1.2", "prefixlen": 16}
                            ],
                        }
                    ]
                ),
            )
        if "ue-pod -- ip -j route show" in remote:
            return CommandResult(
                0,
                json.dumps([{"dst": "12.1.0.0/16", "dev": "tun_srsue1"}]),
            )
        if "upf-pod -- ip -j route show" in remote:
            return CommandResult(
                0,
                json.dumps([{"dst": "12.1.0.0/16", "dev": "ogstun"}]),
            )
        return CommandResult(2, "", "unsupported fake command")


class NetworkVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = load_inventory(FIXTURE)
        self.lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        self.images = golden_path_image_variables(self.lock)

    def test_proves_locked_gnb_srsue_tunnel_and_upf_route(self) -> None:
        runner = VerificationRunner(self.images)
        with patch.dict(
            os.environ,
            {"SYNTHRAN_KNOWN_HOSTS": str(FIXTURE.resolve())},
        ):
            report = verify_network_path(
                inventory=self.inventory,
                lock=self.lock,
                run_id="network-proof",
                runner=runner,
                now=NOW,
            )
        self.assertTrue(report.ready, report.render())
        self.assertEqual("12.1.1.2", report.pdu_address)
        data = report.to_dict()
        self.assertEqual(NETWORK_EVIDENCE_SCHEMA, data["schema"])
        self.assertEqual("tun_srsue1", data["path"]["ue_interface"])
        self.assertEqual("slice1", data["path"]["slice"])
        self.assertTrue(
            next(check for check in report.checks if check.name == "gnb-cell").passed
        )
        for call in runner.calls:
            self.assertIn("BatchMode=yes", call)
            self.assertIn("StrictHostKeyChecking=yes", call)
            self.assertTrue(
                any(
                    part.startswith("UserKnownHostsFile=")
                    for part in call
                )
            )

    def test_rejects_pods_owned_by_another_run(self) -> None:
        runner = VerificationRunner(self.images, run_id="different-run")
        with patch.dict(
            os.environ,
            {"SYNTHRAN_KNOWN_HOSTS": str(FIXTURE.resolve())},
        ):
            report = verify_network_path(
                inventory=self.inventory,
                lock=self.lock,
                run_id="network-proof",
                runner=runner,
                now=NOW,
            )
        self.assertFalse(report.ready)
        self.assertIn("not owned by this run ID", report.render())

    def test_every_runtime_image_is_digest_addressed(self) -> None:
        self.assertEqual(8, len(self.images))
        for reference in self.images.values():
            self.assertRegex(reference, r"@sha256:[0-9a-f]{64}$")


class DeploymentBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = load_inventory(FIXTURE)
        self.lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        self.plan = build_network_plan(
            lock=self.lock,
            inventory=self.inventory,
            profile="default",
        )

    def test_invalid_run_id_cannot_escape_the_run_root(self) -> None:
        with self.assertRaisesRegex(NetworkRuntimeError, "run ID"):
            validate_run_id("../escape")

    def test_sanitizer_removes_credentials_subscribers_private_ips_and_paths(self) -> None:
        private_path = REPOSITORY_ROOT / "private" / "hosts.ini"
        subscriber_id = "00101" + "0000001121"
        subscriber_key = "fec86ba6" + "eb707ed0" + "8905757b" + "1bb44b8f"
        source = (
            f"{private_path} {subscriber_id} {subscriber_key} 192.168.7.9"
        )
        sanitized = sanitize_deployment_text(source, [private_path])
        self.assertNotIn(str(private_path), sanitized)
        self.assertNotIn(subscriber_id, sanitized)
        self.assertNotIn(subscriber_key, sanitized)
        self.assertNotIn("192.168.7.9", sanitized)

    def test_wrapper_uses_only_the_exact_locked_collection(self) -> None:
        requirements = (
            REPOSITORY_ROOT / "deploy" / "ansible" / "requirements.yml"
        ).read_text(encoding="utf-8")
        collection = self.lock.raw["ansible_collections"]["kubernetes_core"]
        self.assertIn(f"name: {collection['name']}", requirements)
        self.assertIn(f'version: "{collection["version"]}"', requirements)
        self.assertNotIn("community.general", requirements)
        wrapper = (
            REPOSITORY_ROOT / "deploy" / "ansible" / "golden-path-deploy.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("playbooks/deploy.yml", wrapper)
        self.assertNotIn("deploy.sh", wrapper)
        self.assertIn("synthran_golden_path_guard: true", wrapper)
        self.assertIn(
            ".synthran/{{ synthran_run_id }}/open5gs-k8s",
            wrapper,
        )
        self.assertIn(
            ".synthran/{{ synthran_run_id }}/srsran-helm",
            wrapper,
        )
        self.assertEqual(2, wrapper.count("Refuse a reused remote"))
        self.assertIn("deployment_option=open5gs", " ".join(self.plan.commands()[-1]))

    def test_golden_path_patch_removes_unsafe_upstream_side_effects(self) -> None:
        boundary_patch = (
            REPOSITORY_ROOT
            / "deploy"
            / "ansible"
            / "patches"
            / "golden-path-boundary.patch"
        ).read_text(encoding="utf-8")
        for expected in (
            "+  when: not synthran_golden_path_guard | default(false) | bool",
            "+  no_log: true",
            "+- name: Refuse an unprepared yq dependency",
            "+- name: Refuse an unprepared Helm dependency",
            "selectattr('name', 'equalto', 'slice1')",
            "if ue_name == 'uesim01'",
        ):
            self.assertIn(expected, boundary_patch)
        for removed_task in (
            "-- name: Deploy Open5GS Web UI",
            "-- name: Run add-admin-account.py",
            "-  ansible.builtin.package:",
        ):
            self.assertIn(removed_task, boundary_patch)

    def test_execution_uses_detached_worktree_and_writes_sanitized_manifest(self) -> None:
        subscriber_id = "00101" + "0000001121"
        subscriber_key = "fec86ba6" + "eb707ed0" + "8905757b" + "1bb44b8f"
        preflight = {
            "owner_fingerprint": "sha256:owner",
            "reservation_fingerprint": "sha256:reservation",
            "allocation_fingerprint": "sha256:allocation",
            "dependency_lock_sha256": "a" * 64,
            "slices_controller": {
                "schema": "synthran/slices-controller/v1alpha1",
                "ready": True,
                "dependency_lock_sha256": "a" * 64,
                "project_fingerprint": "b" * 64,
                "experiment_fingerprint": "c" * 64,
                "python_version": "3.12.11",
                "ansible_version": "2.20.5",
                "pos_version": "2.5.35",
                "slices_cli_version": "1.0.0",
            },
        }
        calls: list[tuple[tuple[str, ...], Path, dict[str, str] | None]] = []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "locked-checkout"
            checkout.mkdir()

            def fake_runner(command, cwd, environment, _timeout):
                argv = tuple(command)
                calls.append(
                    (
                        argv,
                        cwd,
                        dict(environment) if environment is not None else None,
                    )
                )
                if argv[:3] == ("git", "-C", str(checkout)):
                    Path(argv[-2]).mkdir(parents=True)
                    return CommandResult(0, "detached worktree created")
                if argv == ("git", "rev-parse", "HEAD"):
                    return CommandResult(0, self.plan.fiveg_ansible_commit + "\n")
                return CommandResult(
                    0,
                    f"{FIXTURE.resolve()} {subscriber_id} {subscriber_key} 192.168.7.9",
                )

            with (
                patch.dict(
                    os.environ,
                    {"SYNTHRAN_KNOWN_HOSTS": str(FIXTURE.resolve())},
                ),
                patch(
                    "synthran.network_runtime.load_fresh_live_evidence",
                    return_value=preflight,
                ),
                patch(
                    "synthran.network_runtime.validate_fiveg_checkout",
                    return_value=checkout,
                ),
                patch(
                    "synthran.network_runtime.verify_slices_controller",
                    return_value=SimpleNamespace(to_dict=lambda: preflight["slices_controller"]),
                ),
            ):
                result = execute_network_deployment(
                    plan=self.plan,
                    lock=self.lock,
                    dependency_root=root / "deps",
                    live_evidence_path=root / "preflight.json",
                    owner="operator",
                    reservation_id="reservation",
                    allocation_id="allocation",
                    run_id="network-proof",
                    slices_project="project-test",
                    slices_experiment="experiment-test",
                    run_root=root / "runs",
                    repository_root=REPOSITORY_ROOT,
                    runner=fake_runner,
                )

            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(DEPLOYMENT_SCHEMA, manifest["schema"])
            self.assertEqual("deployed-unverified", manifest["status"])
            self.assertEqual("none", manifest["reservation_action"])
            self.assertRegex(
                manifest["overlays"]["ansible_overlay_sha256"],
                r"^[0-9a-f]{64}$",
            )
            log = result.log_path.read_text(encoding="utf-8")
            self.assertNotIn(subscriber_id, log)
            self.assertNotIn(subscriber_key, log)
            self.assertNotIn("192.168.7.9", log)
            worktree_call = calls[0][0]
            self.assertIn("--detach", worktree_call)
            patch_calls = [
                call[0]
                for call in calls
                if call[0][:2] == ("git", "apply")
            ]
            self.assertEqual(2, len(patch_calls))
            self.assertIn("--check", patch_calls[0])
            playbook_call = next(call for call in calls if call[0][0] == "ansible-playbook")
            self.assertIn(
                str(
                    result.run_directory
                    / "worktree"
                    / ".synthran"
                    / "golden-path-deploy.yml"
                ),
                playbook_call[0],
            )
            self.assertEqual("True", playbook_call[2]["ANSIBLE_HOST_KEY_CHECKING"])
            self.assertIn(
                "StrictHostKeyChecking=yes",
                playbook_call[2]["ANSIBLE_SSH_ARGS"],
            )
            self.assertIn(
                "UserKnownHostsFile=",
                playbook_call[2]["ANSIBLE_SSH_ARGS"],
            )

    def test_failed_deployment_keeps_a_sanitized_partial_manifest_and_log(self) -> None:
        subscriber_id = "00101" + "0000001121"
        subscriber_key = "fec86ba6" + "eb707ed0" + "8905757b" + "1bb44b8f"
        preflight = {
            "owner_fingerprint": "sha256:owner",
            "reservation_fingerprint": "sha256:reservation",
            "allocation_fingerprint": "sha256:allocation",
            "dependency_lock_sha256": "a" * 64,
            "slices_controller": {
                "schema": "synthran/slices-controller/v1alpha1",
                "ready": True,
                "dependency_lock_sha256": "a" * 64,
                "project_fingerprint": "b" * 64,
                "experiment_fingerprint": "c" * 64,
                "python_version": "3.12.11",
                "ansible_version": "2.20.5",
                "pos_version": "2.5.35",
                "slices_cli_version": "1.0.0",
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "locked-checkout"
            checkout.mkdir()

            def failing_runner(command, _cwd, _environment, _timeout):
                argv = tuple(command)
                if argv[:3] == ("git", "-C", str(checkout)):
                    Path(argv[-2]).mkdir(parents=True)
                    return CommandResult(0, "detached worktree created")
                if argv == ("git", "rev-parse", "HEAD"):
                    return CommandResult(0, self.plan.fiveg_ansible_commit + "\n")
                if argv[0] == "ansible-playbook" and "--syntax-check" not in argv:
                    return CommandResult(
                        2,
                        f"{subscriber_id} {subscriber_key} 192.168.7.9",
                    )
                return CommandResult(0, "ok")

            with (
                patch.dict(
                    os.environ,
                    {"SYNTHRAN_KNOWN_HOSTS": str(FIXTURE.resolve())},
                ),
                patch(
                    "synthran.network_runtime.load_fresh_live_evidence",
                    return_value=preflight,
                ),
                patch(
                    "synthran.network_runtime.validate_fiveg_checkout",
                    return_value=checkout,
                ),
                patch(
                    "synthran.network_runtime.verify_slices_controller",
                    return_value=SimpleNamespace(to_dict=lambda: preflight["slices_controller"]),
                ),
            ):
                with self.assertRaisesRegex(NetworkRuntimeError, "ansible-deployment"):
                    execute_network_deployment(
                        plan=self.plan,
                        lock=self.lock,
                        dependency_root=root / "deps",
                        live_evidence_path=root / "preflight.json",
                        owner="operator",
                        reservation_id="reservation",
                        allocation_id="allocation",
                        run_id="failed-proof",
                        slices_project="project-test",
                        slices_experiment="experiment-test",
                        run_root=root / "runs",
                        repository_root=REPOSITORY_ROOT,
                        runner=failing_runner,
                    )

            run_directory = root / "runs" / "failed-proof"
            manifest = json.loads(
                (run_directory / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual("failed", manifest["status"])
            self.assertEqual("ansible-deployment", manifest["failure_stage"])
            log = (run_directory / "deployment.log").read_text(encoding="utf-8")
            self.assertNotIn(subscriber_id, log)
            self.assertNotIn(subscriber_key, log)
            self.assertNotIn("192.168.7.9", log)


class ContractSchemaTests(unittest.TestCase):
    def test_network_evidence_and_manifest_schemas_are_valid_json(self) -> None:
        expected = {
            "live-preflight-v1alpha2.schema.json": "synthran/live-preflight/v1alpha2",
            "network-deployment-v1alpha1.schema.json": DEPLOYMENT_SCHEMA,
            "network-evidence-v1alpha1.schema.json": NETWORK_EVIDENCE_SCHEMA,
            "resource-preparation-v1alpha1.schema.json": (
                "synthran/resource-preparation/v1alpha1"
            ),
        }
        for filename, schema_id in expected.items():
            with self.subTest(filename=filename):
                payload = json.loads(
                    (REPOSITORY_ROOT / "contracts" / filename).read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    schema_id,
                    payload["properties"]["schema"]["const"],
                )
                self.assertTrue(payload["$id"].startswith("https://"))
                self.assertEqual("object", payload["type"])


if __name__ == "__main__":
    unittest.main()
