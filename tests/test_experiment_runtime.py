from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
from typing import Sequence
import unittest
from unittest.mock import MagicMock, patch

from synthran.dependencies import load_lock
from synthran.experiment import ExperimentCheck, ExperimentError, ExperimentScenario
from synthran.experiment_runtime import (
    CommandResult,
    _collect_rollout_diagnostics,
    _core_address,
    _discover_ue_deployment,
    _discover_ue_pod,
    _one_name,
    _prepare_cooja_checkout,
    _render_manifest,
    execute_experiment,
)
from synthran.fiveg_ansible import InventoryHost, NetworkInventory, load_inventory
from synthran.network_runtime import NetworkVerificationReport, VerificationCheck
from synthran.resource_runtime import build_preparation_inventory


class ExperimentRuntimeContractTests(unittest.TestCase):
    def test_manifest_never_claims_reservation_or_network_deployment(self) -> None:
        scenario = ExperimentScenario(
            "experiment-01",
            "network-accepted-01",
            "12.1.0.1",
        )
        manifest = _render_manifest(
            scenario,
            status="running",
            scenario_path=Path("scenario.json"),
        )
        self.assertEqual(manifest["reservation_action"], "none")
        self.assertEqual(manifest["network_deployment_action"], "none")
        self.assertEqual(manifest["network_run_id"], "network-accepted-01")
        self.assertEqual(manifest["schema"], "synthran/experiment-run/v1alpha1")

    def test_core_address_requires_literal_live_address(self) -> None:
        inventory_text = """[webshell]
localhost ansible_connection=local

[core_node]
lab-core ansible_host=192.0.2.10 ansible_user=root nic_interface=eth1 ip=192.0.2.10 storage=disk1

[ran_node]
lab-ran ansible_host=192.0.2.11 ansible_user=root nic_interface=eth1 ip=192.0.2.11 storage=disk1 boot_mode=live

[monitor_node]

[sopnodes:children]
core_node
ran_node

[k8s_workers:children]
ran_node

[all:vars]
core="open5gs"
ran="srsRAN"
core_node_name="lab-core"
ran_node_name="lab-ran"
rru="rfsim"
bridge_enabled=true
monitoring_enabled=false
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "hosts.ini"
            path.write_text(inventory_text, encoding="utf-8")
            inventory = load_inventory(path)
            self.assertEqual(_core_address(inventory), "192.0.2.10")

    def test_core_address_accepts_generated_preparation_inventory(self) -> None:
        _text, inventory = build_preparation_inventory(
            core_node="sopnode-f2",
            ran_node="sopnode-f3",
            source=Path("hosts.ini"),
        )
        self.assertEqual(inventory.core_node.name, "sopnode-f2")
        self.assertEqual(inventory.core_node.variables.get("ip"), "172.28.2.77")
        self.assertEqual(_core_address(inventory), "172.28.2.77")

    def test_core_address_missing_ip_raises_experiment_error(self) -> None:
        inventory = NetworkInventory(
            path=Path("hosts.ini"),
            sha256="0" * 64,
            core_node=InventoryHost("lab-core", {}),
            ran_node=InventoryHost("lab-ran", {"ip": "192.0.2.11"}),
            all_vars={},
        )
        with self.assertRaisesRegex(
            ExperimentError,
            "^prepared inventory is missing the core node IP address$",
        ):
            _core_address(inventory)

    def test_core_address_malformed_ip_raises_experiment_error(self) -> None:
        inventory = NetworkInventory(
            path=Path("hosts.ini"),
            sha256="0" * 64,
            core_node=InventoryHost("lab-core", {"ip": "not-an-ip"}),
            ran_node=InventoryHost("lab-ran", {"ip": "192.0.2.11"}),
            all_vars={},
        )
        with self.assertRaisesRegex(
            ExperimentError,
            "^prepared inventory has an invalid core node IP address; expected a literal IPv4 or IPv6 address$",
        ):
            _core_address(inventory)


class CoojaCheckoutPreparationTests(unittest.TestCase):
    def test_prepare_cooja_checkout_scopes_to_tools_cooja_without_recursive(self) -> None:
        contiki = Path("/opt/contiki-ng")
        commands: list[tuple[str, ...]] = []

        def fake_checked(command: tuple[str, ...], **kwargs: object) -> str:
            commands.append(tuple(command))
            if "HEAD:tools/cooja" in command:
                return "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2\n"
            if command[-2:] == ("rev-parse", "HEAD"):
                return "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2\n"
            return ""

        with patch("synthran.experiment_runtime._checked", side_effect=fake_checked):
            target = _prepare_cooja_checkout(contiki)

        self.assertEqual(target, contiki / "tools" / "cooja")
        self.assertEqual(len(commands), 3)

        submodule_cmd = commands[0]
        self.assertEqual(
            submodule_cmd,
            (
                "git",
                "-C",
                str(contiki),
                "submodule",
                "update",
                "--init",
                "--checkout",
                "--",
                "tools/cooja",
            ),
        )
        self.assertIn("tools/cooja", submodule_cmd)
        for cmd in commands:
            self.assertNotIn("--recursive", cmd)

        self.assertEqual(
            commands[1],
            ("git", "-C", str(contiki), "rev-parse", "HEAD:tools/cooja"),
        )
        self.assertEqual(
            commands[2],
            ("git", "-C", str(contiki / "tools" / "cooja"), "rev-parse", "HEAD"),
        )

    def test_prepare_cooja_checkout_accepts_matching_revisions(self) -> None:
        contiki = Path("/opt/contiki-ng")
        revision = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"

        def fake_checked(command: tuple[str, ...], **kwargs: object) -> str:
            if "HEAD:tools/cooja" in command:
                return f"{revision}\n"
            if command[-2:] == ("rev-parse", "HEAD"):
                return f"{revision}\n"
            return ""

        with patch("synthran.experiment_runtime._checked", side_effect=fake_checked):
            target = _prepare_cooja_checkout(contiki)

        self.assertEqual(target, contiki / "tools" / "cooja")

    def test_prepare_cooja_checkout_rejects_mismatched_revisions(self) -> None:
        contiki = Path("/opt/contiki-ng")

        def fake_checked(command: tuple[str, ...], **kwargs: object) -> str:
            if "HEAD:tools/cooja" in command:
                return "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2\n"
            if command[-2:] == ("rev-parse", "HEAD"):
                return "f1e2d3c4b5a6f1e2d3c4b5a6f1e2d3c4b5a6f1e2\n"
            return ""

        with patch("synthran.experiment_runtime._checked", side_effect=fake_checked):
            with self.assertRaisesRegex(
                ExperimentError,
                "^Cooja checkout does not match the revision pinned by Contiki-NG$",
            ):
                _prepare_cooja_checkout(contiki)



class UEDiscoveryTests(unittest.TestCase):
    def _sample_inventory(self) -> NetworkInventory:
        return NetworkInventory(
            path=Path("hosts.ini"),
            sha256="0" * 64,
            core_node=InventoryHost("lab-core", {"ip": "192.0.2.10"}),
            ran_node=InventoryHost("lab-ran", {"ip": "192.0.2.11"}),
            all_vars={},
        )

    def test_discover_ue_deployment_uses_helm_name_and_exact_run_id(self) -> None:
        inventory = self._sample_inventory()
        captured: dict[str, object] = {}

        def fake_remote_json(
            inv: NetworkInventory,
            cmd: str,
            *,
            label: str,
            timeout_seconds: int = 60,
        ) -> dict[str, object]:
            captured["inventory"] = inv
            captured["cmd"] = cmd
            captured["label"] = label
            return {"items": [{"metadata": {"name": "srsran-ue-test-deploy"}}]}

        with patch("synthran.experiment_runtime._remote_json", side_effect=fake_remote_json):
            name = _discover_ue_deployment(inventory, "net-run-12345")

        self.assertEqual(name, "srsran-ue-test-deploy")
        self.assertEqual(captured["label"], "srsUE Deployment discovery")
        cmd_str = str(captured["cmd"])
        self.assertIn("kubectl get deployments", cmd_str)
        self.assertIn("-l app.kubernetes.io/name=srsran-ue,synthran.run/id=net-run-12345", cmd_str)
        self.assertNotIn("app=srsran", cmd_str)
        self.assertNotIn("component=ue", cmd_str)

    def test_discover_ue_pod_continues_to_use_component_ue_and_exact_run_id(self) -> None:
        inventory = self._sample_inventory()
        captured: dict[str, object] = {}

        def fake_remote_json(
            inv: NetworkInventory,
            cmd: str,
            *,
            label: str,
            timeout_seconds: int = 60,
        ) -> dict[str, object]:
            captured["inventory"] = inv
            captured["cmd"] = cmd
            captured["label"] = label
            return {"items": [{"metadata": {"name": "srsran-ue-pod-xyz"}}]}

        with patch("synthran.experiment_runtime._remote_json", side_effect=fake_remote_json):
            name = _discover_ue_pod(inventory, "net-run-12345")

        self.assertEqual(name, "srsran-ue-pod-xyz")
        self.assertEqual(captured["label"], "srsUE pod discovery")
        cmd_str = str(captured["cmd"])
        self.assertIn("kubectl get pods", cmd_str)
        self.assertIn("-l app=srsran,component=ue,synthran.run/id=net-run-12345", cmd_str)


class OneNameExtractionTests(unittest.TestCase):
    def test_one_name_extracts_name_successfully(self) -> None:
        payload = {"items": [{"metadata": {"name": "srsran-ue-resource"}}]}
        name = _one_name(payload, label="run-owned srsUE Deployment")
        self.assertEqual(name, "srsran-ue-resource")

    def test_one_name_fails_when_items_is_not_a_list(self) -> None:
        for malformed_payload in ({}, {"items": None}, {"items": "not-a-list"}, {"items": 123}):
            with self.assertRaisesRegex(
                ExperimentError,
                r"^run-owned srsUE Deployment discovery returned malformed data$",
            ):
                _one_name(malformed_payload, label="run-owned srsUE Deployment")

    def test_one_name_fails_when_no_resource_found(self) -> None:
        with self.assertRaisesRegex(
            ExperimentError,
            r"^no run-owned srsUE Deployment was found$",
        ):
            _one_name({"items": []}, label="run-owned srsUE Deployment")

    def test_one_name_fails_when_multiple_resources_found(self) -> None:
        payload = {
            "items": [
                {"metadata": {"name": "dep-1"}},
                {"metadata": {"name": "dep-2"}},
            ]
        }
        with self.assertRaisesRegex(
            ExperimentError,
            r"^multiple run-owned srsUE Deployment resources were found; refusing to choose one$",
        ):
            _one_name(payload, label="run-owned srsUE Deployment")

    def test_one_name_fails_when_metadata_is_malformed(self) -> None:
        invalid_payloads = (
            {"items": ["not-a-dict"]},
            {"items": [{}]},
            {"items": [{"metadata": "not-a-dict"}]},
            {"items": [{"metadata": {}}]},
            {"items": [{"metadata": {"name": None}}]},
            {"items": [{"metadata": {"name": 12345}}]},
        )
        for payload in invalid_payloads:
            with self.assertRaisesRegex(
                ExperimentError,
                r"^run-owned srsUE Deployment metadata is malformed$",
            ):
                _one_name(payload, label="run-owned srsUE Deployment")

    def test_one_name_ignores_terminating_items_with_deletion_timestamp(self) -> None:
        payload = {
            "items": [
                {
                    "metadata": {
                        "name": "srsran-ue-old",
                        "deletionTimestamp": "2026-08-16T14:00:00Z",
                    }
                },
                {"metadata": {"name": "srsran-ue-active"}},
            ]
        }
        name = _one_name(payload, label="run-owned srsUE pod")
        self.assertEqual(name, "srsran-ue-active")


class RolloutDiagnosticsTests(unittest.TestCase):
    def _sample_inventory(self) -> NetworkInventory:
        return NetworkInventory(
            path=Path("hosts.ini"),
            sha256="0" * 64,
            core_node=InventoryHost(
                "lab-core",
                {"ansible_host": "192.0.2.10", "ansible_user": "root", "ip": "192.0.2.10"},
            ),
            ran_node=InventoryHost(
                "lab-ran",
                {"ansible_host": "192.0.2.11", "ansible_user": "root", "ip": "192.0.2.11"},
            ),
            all_vars={},
        )

    def test_collect_rollout_diagnostics_gathers_and_sanitizes(self) -> None:
        inventory = self._sample_inventory()
        executed_commands: list[Sequence[str]] = []
        subscriber_id = "00101" + "0000001121"
        subscriber_key = "fec86ba6" + "eb707ed0" + "8905757b" + "1bb44b8f"

        def fake_run(
            cmd: Sequence[str],
            *,
            timeout_seconds: int = 60,
            cwd: Path | None = None,
            input_text: str | None = None,
        ) -> CommandResult:
            executed_commands.append(cmd)
            cmd_str = " ".join(cmd)
            if "jsonpath=" in cmd_str:
                return CommandResult(0, "srsran-ue-pod-abc12", "")
            if "describe pod" in cmd_str:
                return CommandResult(
                    0,
                    f"Pod: srsran-ue-pod-abc12 hex {subscriber_key}",
                    "",
                )
            if "logs" in cmd_str:
                return CommandResult(
                    0,
                    f"Mosquitto starting on 192.168.1.50 id: {subscriber_id}",
                    "",
                )
            if "get events" in cmd_str:
                return CommandResult(0, "Event: BackOff FailedScheduling", "")
            return CommandResult(
                0,
                "NAME READY STATUS\nsrsran-ue-pod-abc12 1/2 CrashLoopBackOff",
                "",
            )

        with tempfile.TemporaryDirectory() as temporary:
            known_hosts = Path(temporary) / "known_hosts"
            known_hosts.write_text("lab-core ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...\n", encoding="utf-8")
            log_path = Path(temporary) / "logs" / "srsue-mqtt-rollout-diagnostics.log"
            private_path = Path(temporary) / "secret-path"
            with (
                patch.dict("os.environ", {"SYNTHRAN_KNOWN_HOSTS": str(known_hosts)}),
                patch("synthran.experiment_runtime._run", side_effect=fake_run),
            ):
                _collect_rollout_diagnostics(
                    inventory,
                    network_run_id="net-run-12345",
                    log_path=log_path,
                    private_paths=(private_path,),
                )

            self.assertTrue(log_path.is_file())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("=== SynthRAN Rollout Diagnostics", content)
            self.assertIn("=== kubectl get pods (srsran-ue) ===", content)
            self.assertIn("=== kubectl get events ===", content)
            self.assertIn("=== kubectl describe pod srsran-ue-pod-abc12 ===", content)
            self.assertIn(
                "=== kubectl logs srsran-ue-pod-abc12 -c synthran-edge-mqtt --tail=100 ===",
                content,
            )
            # Check sanitization:
            self.assertNotIn(subscriber_key, content)
            self.assertIn("<secret>", content)
            self.assertNotIn(subscriber_id, content)
            self.assertIn("<subscriber-id>", content)
            self.assertNotIn("192.168.1.50", content)
            self.assertIn("<private-ip>", content)

            # Verify executed commands contain expected kubectl calls:
            flattened = " ".join(" ".join(c) for c in executed_commands)
            self.assertIn(
                "kubectl get pods -n open5gs -l app=srsran,component=ue,synthran.run/id=net-run-12345",
                flattened,
            )
            self.assertIn("kubectl describe pod srsran-ue-pod-abc12 -n open5gs", flattened)
            self.assertIn(
                "kubectl logs srsran-ue-pod-abc12 -n open5gs -c synthran-edge-mqtt --tail=100",
                flattened,
            )

    def test_execute_experiment_rollout_failure_preserves_diagnostics_and_fails_cleanly(
        self,
    ) -> None:
        inventory = self._sample_inventory()
        progress_buffer = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            known_hosts = root / "known_hosts"
            known_hosts.write_text("lab-core ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...\n", encoding="utf-8")
            network_dir = root / "runs" / "net-01"
            network_dir.mkdir(parents=True)
            manifest_path = network_dir / "manifest.json"
            evidence_path = network_dir / "network-evidence.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": "synthran/network-deployment/v1alpha1",
                        "run_id": "net-01",
                        "status": "path-proven",
                        "network_evidence": evidence_path.name,
                    }
                ),
                encoding="utf-8",
            )
            evidence_path.write_text(
                json.dumps(
                    {
                        "schema": "synthran/network-evidence/v1alpha1",
                        "run_id": "net-01",
                        "ready": True,
                        "path": {
                            "pdu_address": "12.1.0.1",
                            "pdu_network": "12.1.0.0/16",
                            "ue_interface": "tun_srsue1",
                            "slice": "slice1",
                            "sst": 1,
                            "dnn": "internet",
                        },
                        "checks": [{"name": "upf-path", "passed": True}],
                    }
                ),
                encoding="utf-8",
            )
            lock = load_lock(Path("dependencies.lock.yml"))

            with (
                patch("sys.platform", "linux"),
                patch.dict(
                    "os.environ",
                    {
                        "CONDA_DEFAULT_ENV": "synthran",
                        "SYNTHRAN_KNOWN_HOSTS": str(known_hosts),
                    },
                ),
                patch(
                    "synthran.experiment_runtime.verify_network_path",
                    return_value=MagicMock(ready=True),
                ),
                patch(
                    "synthran.experiment_runtime._validate_contiki_checkout",
                    return_value=root / "contiki",
                ),
                patch("synthran.experiment_runtime._prepare_cooja_checkout"),
                patch("synthran.experiment_runtime._checked"),
                patch(
                    "synthran.experiment_runtime._discover_ue_deployment",
                    return_value="srsran-ue-deploy",
                ),
                patch("synthran.experiment_runtime._kubectl_apply_object"),
                patch("synthran.experiment_runtime._remote"),
                patch("synthran.experiment_runtime._kubectl_patch_deployment"),
                patch(
                    "synthran.experiment_runtime._wait_rollout",
                    side_effect=ExperimentError("srsUE MQTT rollout failed"),
                ),
                patch(
                    "synthran.experiment_runtime._collect_rollout_diagnostics"
                ) as mock_diagnostics,
                patch(
                    "synthran.experiment_runtime._cleanup_live_resources",
                    return_value=ExperimentCheck("cleanup", True, "cleaned up"),
                ),
            ):
                result = execute_experiment(
                    inventory=inventory,
                    lock=lock,
                    dependency_root=root / "deps",
                    network_manifest=manifest_path,
                    network_evidence=evidence_path,
                    run_id="exp-rollout-fail",
                    repository_root=Path(__file__).parent.parent,
                    run_root=root / "experiments",
                    progress=progress_buffer,
                )

                self.assertFalse(result.ready)
                mock_diagnostics.assert_called_once()
                output = progress_buffer.getvalue()
                self.assertIn("[synthran] srsUE MQTT rollout: FAILED", output)
                self.assertIn(
                    "[synthran] error: edge MQTT sidecar did not become Ready; diagnostic log saved",
                    output,
                )
                self.assertIn("[synthran] experiment path NOT PROVEN", output)

                manifest_file = result.run_directory / "manifest.json"
                self.assertTrue(manifest_file.is_file())
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                self.assertEqual(manifest_data["status"], "failed")
                self.assertEqual(
                    manifest_data["failure"],
                    "edge MQTT sidecar did not become Ready; diagnostic log saved",
                )

    def test_execute_experiment_post_patch_verification_failure_renders_checks_and_saves_diagnostics(
        self,
    ) -> None:
        inventory = self._sample_inventory()
        progress_buffer = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            known_hosts = root / "known_hosts"
            known_hosts.write_text("lab-core ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...\n", encoding="utf-8")
            network_dir = root / "runs" / "net-01"
            network_dir.mkdir(parents=True)
            manifest_path = network_dir / "manifest.json"
            evidence_path = network_dir / "network-evidence.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": "synthran/network-deployment/v1alpha1",
                        "run_id": "net-01",
                        "status": "path-proven",
                        "network_evidence": evidence_path.name,
                    }
                ),
                encoding="utf-8",
            )
            evidence_path.write_text(
                json.dumps(
                    {
                        "schema": "synthran/network-evidence/v1alpha1",
                        "run_id": "net-01",
                        "ready": True,
                        "path": {
                            "pdu_address": "12.1.0.1",
                            "pdu_network": "12.1.0.0/16",
                            "ue_interface": "tun_srsue1",
                            "slice": "slice1",
                            "sst": 1,
                            "dnn": "internet",
                        },
                        "checks": [{"name": "upf-path", "passed": True}],
                    }
                ),
                encoding="utf-8",
            )
            lock = load_lock(Path("dependencies.lock.yml"))

            failed_checks = (
                VerificationCheck("gnb", True, "one run-owned pod has healthy digest-locked containers"),
                VerificationCheck("srsue", False, "srsue pod is not owned by this run ID"),
                VerificationCheck("slice1-upf", True, "one run-owned pod has healthy digest-locked containers"),
                VerificationCheck("ue-tunnel", False, "not probed because the srsUE pod check failed"),
            )
            failed_verification = NetworkVerificationReport(
                run_id="net-01",
                generated_at_utc=datetime(2026, 8, 16, 14, 0, tzinfo=timezone.utc),
                inventory_sha256="0" * 64,
                dependencies={},
                checks=failed_checks,
            )

            call_count = 0

            def mock_verify(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return MagicMock(ready=True)
                if call_count == 2:
                    return failed_verification
                return MagicMock(ready=True)

            with (
                patch("sys.platform", "linux"),
                patch.dict(
                    "os.environ",
                    {
                        "CONDA_DEFAULT_ENV": "synthran",
                        "SYNTHRAN_KNOWN_HOSTS": str(known_hosts),
                    },
                ),
                patch(
                    "synthran.experiment_runtime.verify_network_path",
                    side_effect=mock_verify,
                ),
                patch(
                    "synthran.experiment_runtime._validate_contiki_checkout",
                    return_value=root / "contiki",
                ),
                patch("synthran.experiment_runtime._prepare_cooja_checkout"),
                patch("synthran.experiment_runtime._checked"),
                patch(
                    "synthran.experiment_runtime._discover_ue_deployment",
                    return_value="srsran-ue-deploy",
                ),
                patch("synthran.experiment_runtime._kubectl_apply_object"),
                patch("synthran.experiment_runtime._remote"),
                patch("synthran.experiment_runtime._kubectl_patch_deployment"),
                patch("synthran.experiment_runtime._wait_rollout"),
                patch(
                    "synthran.experiment_runtime._discover_ue_pod",
                    return_value="srsran-ue-pod",
                ),
                patch(
                    "synthran.experiment_runtime._collect_rollout_diagnostics"
                ) as mock_diagnostics,
                patch(
                    "synthran.experiment_runtime._cleanup_live_resources",
                    return_value=ExperimentCheck("cleanup", True, "cleaned up"),
                ),
            ):
                result = execute_experiment(
                    inventory=inventory,
                    lock=lock,
                    dependency_root=root / "deps",
                    network_manifest=manifest_path,
                    network_evidence=evidence_path,
                    run_id="exp-postpatch-fail",
                    repository_root=Path(__file__).parent.parent,
                    run_root=root / "experiments",
                    progress=progress_buffer,
                )

                self.assertFalse(result.ready)
                mock_diagnostics.assert_called_once()
                self.assertEqual(
                    mock_diagnostics.call_args.kwargs.get("verification"),
                    failed_verification,
                )
                output = progress_buffer.getvalue()
                self.assertIn(
                    "[synthran] srsUE post-patch network verification: FAILED", output
                )
                self.assertIn("[synthran] [PASS] gnb", output)
                self.assertIn(
                    "[synthran] [FAIL] srsue: srsue pod is not owned by this run ID",
                    output,
                )
                self.assertIn("[synthran] [PASS] slice1-upf", output)
                self.assertIn(
                    "[synthran] [FAIL] ue-tunnel: not probed because the srsUE pod check failed",
                    output,
                )
                self.assertIn("[synthran] experiment path NOT PROVEN", output)

                manifest_file = result.run_directory / "manifest.json"
                self.assertTrue(manifest_file.is_file())
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                self.assertEqual(manifest_data["status"], "failed")
                self.assertIn(
                    "srsue: srsue pod is not owned by this run ID",
                    manifest_data["failure"],
                )


if __name__ == "__main__":
    unittest.main()
