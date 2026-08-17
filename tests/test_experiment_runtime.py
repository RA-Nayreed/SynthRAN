from __future__ import annotations

from collections import namedtuple
from contextlib import ExitStack
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import signal
import tempfile
from typing import Sequence
import unittest
from unittest.mock import MagicMock, patch

UnameResult = namedtuple("UnameResult", ["sysname", "nodename", "release", "version", "machine"])
FAKE_UNAME = UnameResult("Linux", "duckburg", "6.5.0", "1", "x86_64")

from synthran.dependencies import load_lock
from synthran.experiment import (
    ExperimentCheck,
    ExperimentError,
    ExperimentScenario,
    TelemetryEvent,
)
from synthran.experiment_runtime import (
    CommandResult,
    ManagedProcess,
    _cleanup_live_resources,
    _collect_rollout_diagnostics,
    _copy_sensor_source,
    _core_address,
    _discover_ue_deployment,
    _discover_ue_pod,
    _one_name,
    _prepare_cooja_checkout,
    _probe_experiment_host,
    _render_manifest,
    _ssh_reverse_tunnel_command,
    _ssh_tunnel_command,
    _validate_java_runtime,
    _wait_tcp,
    execute_experiment,
)
from synthran.fiveg_ansible import InventoryHost, NetworkInventory, load_inventory
from synthran.network_runtime import NetworkVerificationReport, VerificationCheck
from synthran.resource_runtime import build_preparation_inventory
from synthran.rfsim_runtime import RfsimRuntimeState


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


class ExperimentHostCapabilityProbeTests(unittest.TestCase):
    def _sample_inventory(self, host_name: str = "sopnode-f2") -> NetworkInventory:
        return NetworkInventory(
            path=Path("hosts.ini"),
            sha256="0" * 64,
            core_node=InventoryHost(
                host_name,
                {"ansible_host": "192.0.2.10", "ansible_user": "root", "ip": "192.0.2.10"},
            ),
            ran_node=InventoryHost(
                "sopnode-f3",
                {"ansible_host": "192.0.2.11", "ansible_user": "root", "ip": "192.0.2.11"},
            ),
            all_vars={},
        )

    def test_probe_passes_on_valid_root_environment(self) -> None:
        inventory = self._sample_inventory()
        valid_response = json.dumps(
            {
                "uid": 0,
                "tun_dev": True,
                "tun_exists": False,
                "missing_tools": [],
                "busy_ports": [],
            }
        )
        with (
            patch.dict("os.environ", {"SYNTHRAN_KNOWN_HOSTS": "/dev/null"}),
            patch("pathlib.Path.is_file", return_value=True),
            patch(
                "synthran.experiment_runtime._run",
                return_value=CommandResult(0, valid_response, ""),
            ),
        ):
            _probe_experiment_host(inventory)

    def test_probe_fails_closed_when_non_root(self) -> None:
        inventory = self._sample_inventory()
        non_root_response = json.dumps(
            {
                "uid": 1000,
                "tun_dev": True,
                "tun_exists": False,
                "missing_tools": [],
                "busy_ports": [],
            }
        )
        with (
            patch.dict("os.environ", {"SYNTHRAN_KNOWN_HOSTS": "/dev/null"}),
            patch("pathlib.Path.is_file", return_value=True),
            patch(
                "synthran.experiment_runtime._run",
                return_value=CommandResult(0, non_root_response, ""),
            ),
        ):
            with self.assertRaisesRegex(
                ExperimentError,
                r"\[FAIL\] experiment-host: remote host user is not root \(uid=1000\)",
            ):
                _probe_experiment_host(inventory)

    def test_probe_fails_closed_when_tun_dev_missing(self) -> None:
        inventory = self._sample_inventory()
        no_tun_response = json.dumps(
            {
                "uid": 0,
                "tun_dev": False,
                "tun_exists": False,
                "missing_tools": [],
                "busy_ports": [],
            }
        )
        with (
            patch.dict("os.environ", {"SYNTHRAN_KNOWN_HOSTS": "/dev/null"}),
            patch("pathlib.Path.is_file", return_value=True),
            patch(
                "synthran.experiment_runtime._run",
                return_value=CommandResult(0, no_tun_response, ""),
            ),
        ):
            with self.assertRaisesRegex(
                ExperimentError,
                r"\[FAIL\] experiment-host: /dev/net/tun is unavailable on sopnode-f2",
            ):
                _probe_experiment_host(inventory)

    def test_probe_fails_closed_when_tools_missing(self) -> None:
        inventory = self._sample_inventory()
        missing_tools_response = json.dumps(
            {
                "uid": 0,
                "tun_dev": True,
                "tun_exists": False,
                "missing_tools": ["gcc", "make"],
                "busy_ports": [],
            }
        )
        with (
            patch.dict("os.environ", {"SYNTHRAN_KNOWN_HOSTS": "/dev/null"}),
            patch("pathlib.Path.is_file", return_value=True),
            patch(
                "synthran.experiment_runtime._run",
                return_value=CommandResult(0, missing_tools_response, ""),
            ),
        ):
            with self.assertRaisesRegex(
                ExperimentError,
                r"\[FAIL\] experiment-host: required tools \['gcc', 'make'\] are missing on sopnode-f2",
            ):
                _probe_experiment_host(inventory)

    def test_probe_fails_closed_when_tun0_already_exists(self) -> None:
        inventory = self._sample_inventory()
        tun0_exists_response = json.dumps(
            {
                "uid": 0,
                "tun_dev": True,
                "tun_exists": True,
                "missing_tools": [],
                "busy_ports": [],
            }
        )
        with (
            patch.dict("os.environ", {"SYNTHRAN_KNOWN_HOSTS": "/dev/null"}),
            patch("pathlib.Path.is_file", return_value=True),
            patch(
                "synthran.experiment_runtime._run",
                return_value=CommandResult(0, tun0_exists_response, ""),
            ),
        ):
            with self.assertRaisesRegex(
                ExperimentError,
                r"\[FAIL\] experiment-host: tun0 already exists on sopnode-f2; refusing to adopt or delete it",
            ):
                _probe_experiment_host(inventory)

    def test_probe_fails_closed_when_required_port_is_busy(self) -> None:
        inventory = self._sample_inventory()
        busy_port_response = json.dumps(
            {
                "uid": 0,
                "tun_dev": True,
                "tun_exists": False,
                "missing_tools": [],
                "busy_ports": [60001],
            }
        )
        with (
            patch.dict("os.environ", {"SYNTHRAN_KNOWN_HOSTS": "/dev/null"}),
            patch("pathlib.Path.is_file", return_value=True),
            patch(
                "synthran.experiment_runtime._run",
                return_value=CommandResult(0, busy_port_response, ""),
            ),
        ):
            with self.assertRaisesRegex(
                ExperimentError,
                r"\[FAIL\] experiment-host: required ports \[60001\] are already in use on sopnode-f2",
            ):
                _probe_experiment_host(inventory)


class ReverseTunnelTests(unittest.TestCase):
    def test_reverse_tunnel_is_strictly_loopback_bound(self) -> None:
        inventory = NetworkInventory(
            path=Path("hosts.ini"),
            sha256="0" * 64,
            core_node=InventoryHost(
                "sopnode-f2",
                {"ansible_host": "192.0.2.10", "ansible_user": "root", "ip": "192.0.2.10"},
            ),
            ran_node=InventoryHost("sopnode-f3", {"ip": "192.0.2.11"}),
            all_vars={},
        )
        with (
            patch.dict("os.environ", {"SYNTHRAN_KNOWN_HOSTS": "/tmp/known_hosts"}),
            patch("pathlib.Path.is_file", return_value=True),
        ):
            cmd = _ssh_reverse_tunnel_command(inventory, remote_port=60001, local_port=60001)

        self.assertIn("-N", cmd)
        self.assertIn("ExitOnForwardFailure=yes", cmd)
        self.assertIn("-R", cmd)
        self.assertIn("127.0.0.1:60001:127.0.0.1:60001", cmd)
        self.assertNotIn("0.0.0.0", cmd)
        self.assertNotIn("::", cmd)
        self.assertIn("root@192.0.2.10", cmd)


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
                return CommandResult(0, f"Pod: srsran-ue-pod-abc12 hex {subscriber_key}", "")
            if "logs" in cmd_str:
                return CommandResult(0, f"Mosquitto starting on 192.168.1.50 id: {subscriber_id}", "")
            if "get events" in cmd_str:
                return CommandResult(0, "Event: BackOff FailedScheduling", "")
            return CommandResult(
                0,
                "NAME READY STATUS\nsrsran-ue-pod-abc12 1/2 CrashLoopBackOff",
                "",
            )

        with tempfile.TemporaryDirectory() as temporary:
            known_hosts = Path(temporary) / "known_hosts"
            known_hosts.write_text(
                "lab-core ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...\n",
                encoding="utf-8",
            )
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
            self.assertNotIn(subscriber_key, content)
            self.assertIn("<secret>", content)


class FullRemoteExperimentRuntimeTests(unittest.TestCase):
    def _sample_inventory(self, core_name: str = "sopnode-f2") -> NetworkInventory:
        return NetworkInventory(
            path=Path("hosts.ini"),
            sha256="0" * 64,
            core_node=InventoryHost(
                core_name,
                {"ansible_host": "172.28.2.77", "ansible_user": "root", "ip": "172.28.2.77"},
            ),
            ran_node=InventoryHost(
                "sopnode-f3",
                {"ansible_host": "172.28.2.78", "ansible_user": "root", "ip": "172.28.2.78"},
            ),
            all_vars={},
        )

    def _network_artifacts(self, root: Path) -> tuple[Path, Path]:
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
        return manifest_path, evidence_path

    def test_full_experiment_success_path(self) -> None:
        inventory = self._sample_inventory("sopnode-f2")
        progress_buffer = io.StringIO()
        commands_executed: list[tuple[str, ...]] = []

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            known_hosts = root / "known_hosts"
            known_hosts.write_text("sopnode-f2 ssh-ed25519 AAA...\n", encoding="utf-8")
            manifest_path, evidence_path = self._network_artifacts(root)
            lock = load_lock(Path("dependencies.lock.yml"))

            contiki_path = root / "contiki"
            (contiki_path / "tools" / "serial-io").mkdir(parents=True)
            (contiki_path / "tools" / "serial-io" / "Makefile").write_text("all:\n", encoding="utf-8")
            (contiki_path / "tools" / "serial-io" / "tunslip6.c").write_text("int main(){}\n", encoding="utf-8")
            java_home_path = root / "jvm_home"
            java_home_path.mkdir(parents=True)

            mock_cooja_proc = MagicMock()
            mock_cooja_proc.poll.return_value = 0

            # Mock telemetry file generation
            def mock_collect(scenario, *args, **kwargs):
                jsonl_path = kwargs.get("jsonl_path")
                if jsonl_path:
                    lines = []
                    for s_id in range(1, 11):
                        for seq in range(1, 4):
                            ev = TelemetryEvent(
                                run_id=scenario.run_id,
                                sensor_id=f"sensor-{s_id:02d}",
                                sequence=seq,
                                sensor_time_ms=1000 * seq,
                                value_milli=1000 + seq,
                            )
                            lines.append(json.dumps(ev.to_record(received_at_utc=datetime(2026, 8, 17, tzinfo=timezone.utc))))
                    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                res = MagicMock()
                res.completed = True
                res.records = 30
                res.sensors = 10
                return res

            with ExitStack() as stack:
                stack.enter_context(patch("sys.platform", "linux"))
                stack.enter_context(patch.object(os, "uname", return_value=FAKE_UNAME, create=True))
                stack.enter_context(patch.dict("os.environ", {"CONDA_DEFAULT_ENV": "synthran", "SYNTHRAN_KNOWN_HOSTS": str(known_hosts)}))
                stack.enter_context(patch("synthran.experiment_runtime.verify_network_path", return_value=MagicMock(ready=True)))
                stack.enter_context(patch("synthran.experiment_runtime._validate_contiki_checkout", return_value=contiki_path))
                stack.enter_context(patch("synthran.experiment_runtime._validate_java_runtime", return_value=java_home_path))
                stack.enter_context(patch("synthran.experiment_runtime._prepare_cooja_checkout"))
                stack.enter_context(patch("synthran.experiment_runtime._probe_experiment_host"))

                # Track remote calls
                def fake_remote(inv, *cmd, **kwargs):
                    commands_executed.append(cmd)
                    return ""

                def fake_remote_json(inv, cmd, **kwargs):
                    if "ingress-snapshot" in cmd:
                        return {"accepted_connections": 10, "upstream_bytes": 4500, "downstream_bytes": 1200}
                    if "kubectl get deployments" in cmd:
                        return {"items": [{"metadata": {"name": "srsran-ue-deploy"}}]}
                    if "kubectl get pods" in cmd:
                        return {"items": [{"metadata": {"name": "srsran-ue-pod"}}]}
                    return {}

                stack.enter_context(patch("synthran.experiment_runtime._remote", side_effect=fake_remote))
                stack.enter_context(patch("synthran.experiment_runtime._remote_json", side_effect=fake_remote_json))
                stack.enter_context(patch("synthran.experiment_runtime._transfer_directory"))
                stack.enter_context(patch("synthran.experiment_runtime._transfer_file"))
                stack.enter_context(patch("synthran.experiment_runtime._kubectl_apply_object"))
                stack.enter_context(patch("synthran.experiment_runtime._kubectl_patch_deployment"))
                stack.enter_context(patch("synthran.experiment_runtime._wait_rollout"))
                stack.enter_context(
                    patch(
                        "synthran.experiment_runtime.reconcile_rfsim_runtime",
                        return_value=RfsimRuntimeState("srsran-ue-pod", "srsran-gnb-pod", "srsran-gnb", "12.1.0.2"),
                    )
                )
                stack.enter_context(patch("synthran.experiment_runtime._replace_edge_runtime_config"))
                stack.enter_context(patch("synthran.experiment_runtime._restart_edge_sidecar"))
                stack.enter_context(patch("synthran.experiment_runtime._add_ue_route"))

                counter_vals = [100, 100, 500, 200]  # tx_before, rx_before, tx_after, rx_after
                stack.enter_context(patch("synthran.experiment_runtime._interface_counter", side_effect=lambda *args: counter_vals.pop(0)))
                stack.enter_context(patch("synthran.experiment_runtime.time.sleep"))

                mock_proc = MagicMock()
                mock_proc.poll.return_value = None
                mock_stream = MagicMock()
                mock_start_proc = stack.enter_context(
                    patch(
                        "synthran.experiment_runtime._start_process",
                        return_value=ManagedProcess("test", mock_proc, root / "test.log", mock_stream),
                    )
                )
                stack.enter_context(patch("synthran.experiment_runtime._wait_tcp"))

                # Remote tun0 address check: returns 0 with fd00::1
                def fake_run(cmd, *args, **kwargs):
                    cmd_str = " ".join(cmd)
                    if "ip -j address show dev tun0" in cmd_str or "show dev tun0" in cmd_str:
                        return CommandResult(0, '[{"addr_info":[{"local":"fd00::1"}]}]', "")
                    return CommandResult(0, "", "")

                stack.enter_context(patch("synthran.experiment_runtime._run", side_effect=fake_run))
                stack.enter_context(patch("synthran.experiment_runtime.collect_mqtt", side_effect=mock_collect))
                stack.enter_context(
                    patch(
                        "synthran.experiment_runtime._cleanup_live_resources",
                        return_value=ExperimentCheck(
                            "cleanup-base-network",
                            True,
                            "experiment resources removed and accepted network path reproven",
                        ),
                    )
                )

                result = execute_experiment(
                    inventory=inventory,
                    lock=lock,
                    dependency_root=root / "deps",
                    network_manifest=manifest_path,
                    network_evidence=evidence_path,
                    run_id="iot-acceptance-test",
                    repository_root=Path(__file__).parent.parent,
                    run_root=root / "experiments",
                    progress=progress_buffer,
                )

            if not result.ready:
                print("DEBUG OUTPUT:\n", progress_buffer.getvalue())
                manifest_file = result.run_directory / "manifest.json"
                if manifest_file.is_file():
                    print("MANIFEST:\n", manifest_file.read_text(encoding="utf-8"))
            self.assertTrue(result.ready)
            output = progress_buffer.getvalue()
            self.assertIn("[synthran] experiment: iot-acceptance-test", output)
            self.assertIn("[synthran] network prerequisite: OK", output)
            self.assertIn("[synthran] experiment host: checking sopnode-f2...", output)
            self.assertIn("[synthran] experiment host: OK", output)
            self.assertIn("[synthran] Cooja dependency: OK", output)
            self.assertIn("[synthran] remote tunslip6 build: OK", output)
            self.assertIn("[synthran] accepted PDU: 12.1.0.1", output)
            self.assertIn("[synthran] runtime PDU: 12.1.0.2", output)
            self.assertIn("[synthran] serial bridge: ready on sopnode-f2", output)
            self.assertIn("[synthran] RPL border router: tun0 ready", output)
            self.assertIn("[synthran] collector: OK (30 events from 10 sensors)", output)
            self.assertIn("[synthran] [PASS] cleanup-base-network: experiment resources removed and accepted network path reproven", output)
            self.assertIn("[synthran] IOT-TO-5G PATH PROVEN", output)

            # Confirm NO sudo command was run
            for call in mock_start_proc.call_args_list:
                cmd_args = call[0][1]
                cmd_flat = " ".join(cmd_args) if isinstance(cmd_args, (list, tuple)) else str(cmd_args)
                self.assertNotIn("sudo", cmd_flat)

    def test_early_tunslip_exit_fails_immediately_and_prints_cleanup(self) -> None:
        inventory = self._sample_inventory("sopnode-f2")
        progress_buffer = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            known_hosts = root / "known_hosts"
            known_hosts.write_text("sopnode-f2 ssh-ed25519 AAA...\n", encoding="utf-8")
            manifest_path, evidence_path = self._network_artifacts(root)
            lock = load_lock(Path("dependencies.lock.yml"))

            contiki_path = root / "contiki"
            (contiki_path / "tools" / "serial-io").mkdir(parents=True)
            (contiki_path / "tools" / "serial-io" / "Makefile").write_text("all:\n", encoding="utf-8")
            (contiki_path / "tools" / "serial-io" / "tunslip6.c").write_text("int main(){}\n", encoding="utf-8")
            java_home_path = root / "jvm_home"
            java_home_path.mkdir(parents=True)

            with ExitStack() as stack:
                stack.enter_context(patch("sys.platform", "linux"))
                stack.enter_context(patch.object(os, "uname", return_value=FAKE_UNAME, create=True))
                stack.enter_context(patch.dict("os.environ", {"CONDA_DEFAULT_ENV": "synthran", "SYNTHRAN_KNOWN_HOSTS": str(known_hosts)}))
                stack.enter_context(patch("synthran.experiment_runtime.verify_network_path", return_value=MagicMock(ready=True)))
                stack.enter_context(patch("synthran.experiment_runtime._validate_contiki_checkout", return_value=contiki_path))
                stack.enter_context(patch("synthran.experiment_runtime._validate_java_runtime", return_value=java_home_path))
                stack.enter_context(patch("synthran.experiment_runtime._prepare_cooja_checkout"))
                stack.enter_context(patch("synthran.experiment_runtime._probe_experiment_host"))
                stack.enter_context(patch("synthran.experiment_runtime._remote", return_value=""))
                stack.enter_context(patch("synthran.experiment_runtime._remote_json", return_value={"items": [{"metadata": {"name": "ue-res"}}]}))
                stack.enter_context(patch("synthran.experiment_runtime._transfer_directory"))
                stack.enter_context(patch("synthran.experiment_runtime._transfer_file"))
                stack.enter_context(patch("synthran.experiment_runtime._kubectl_apply_object"))
                stack.enter_context(patch("synthran.experiment_runtime._kubectl_patch_deployment"))
                stack.enter_context(patch("synthran.experiment_runtime._wait_rollout"))
                stack.enter_context(
                    patch(
                        "synthran.experiment_runtime.reconcile_rfsim_runtime",
                        return_value=RfsimRuntimeState("srsran-ue-pod", "srsran-gnb-pod", "srsran-gnb", "12.1.0.2"),
                    )
                )
                stack.enter_context(patch("synthran.experiment_runtime._replace_edge_runtime_config"))
                stack.enter_context(patch("synthran.experiment_runtime._restart_edge_sidecar"))
                stack.enter_context(patch("synthran.experiment_runtime._add_ue_route"))
                stack.enter_context(patch("synthran.experiment_runtime._interface_counter", return_value=0))
                stack.enter_context(patch("synthran.experiment_runtime.time.sleep"))

                # Mock tunslip process that exits with code 1
                mock_tunslip_proc = MagicMock()
                mock_tunslip_proc.poll.return_value = 1
                mock_healthy_proc = MagicMock()
                mock_healthy_proc.poll.return_value = None

                def mock_start(name, *args, **kwargs):
                    if name == "tunslip6":
                        return ManagedProcess(name, mock_tunslip_proc, root / "tunslip6.log", MagicMock())
                    return ManagedProcess(name, mock_healthy_proc, root / f"{name}.log", MagicMock())

                stack.enter_context(patch("synthran.experiment_runtime._start_process", side_effect=mock_start))
                stack.enter_context(patch("synthran.experiment_runtime._wait_tcp"))
                stack.enter_context(patch("synthran.experiment_runtime._run", return_value=CommandResult(1, "", "no dev")))
                stack.enter_context(
                    patch(
                        "synthran.experiment_runtime._cleanup_live_resources",
                        return_value=ExperimentCheck(
                            "cleanup-base-network",
                            True,
                            "experiment resources removed and accepted network path reproven",
                        ),
                    )
                )

                result = execute_experiment(
                    inventory=inventory,
                    lock=lock,
                    dependency_root=root / "deps",
                    network_manifest=manifest_path,
                    network_evidence=evidence_path,
                    run_id="iot-tunslip-fail",
                    repository_root=Path(__file__).parent.parent,
                    run_root=root / "experiments",
                    progress=progress_buffer,
                )

            self.assertFalse(result.ready)
            output = progress_buffer.getvalue()
            self.assertIn("[FAIL] serial bridge: remote tunslip6 exited", output)
            self.assertIn("host: sopnode-f2", output)
            self.assertIn("[PASS] cleanup-base-network: experiment resources removed and accepted network path reproven", output)
            self.assertIn("experiment path NOT PROVEN", output)


class ExperimentPrerequisitesTests(unittest.TestCase):
    def test_copy_sensor_source_copies_all_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "deploy" / "iot" / "sensor"
            source.mkdir(parents=True)
            (source / "Makefile").write_text("all:\n", encoding="utf-8")
            (source / "synthran-sensor.c").write_text("int main(){}\n", encoding="utf-8")
            (source / "project-conf.h").write_text("#define UIP_CONF_TCP 1\n", encoding="utf-8")

            run_dir = root / "runs" / "exp-01"
            _copy_sensor_source(root, run_dir)

            dest = run_dir / "sensor"
            self.assertTrue((dest / "Makefile").is_file())
            self.assertTrue((dest / "synthran-sensor.c").is_file())
            self.assertTrue((dest / "project-conf.h").is_file())
            self.assertEqual(
                (dest / "project-conf.h").read_text(encoding="utf-8"),
                "#define UIP_CONF_TCP 1\n",
            )

    def test_validate_java_runtime_accepts_java_21_on_stderr_and_derives_java_home(self) -> None:
        fake_result = MagicMock(returncode=0, stdout="", stderr='openjdk version "21.0.9" 2025-01-21\nOpenJDK Runtime Environment\n')
        with tempfile.TemporaryDirectory() as temporary:
            fake_bin = Path(temporary) / "env" / "bin" / "java"
            fake_bin.parent.mkdir(parents=True)
            fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
            with (
                patch("shutil.which", return_value=str(fake_bin)),
                patch("subprocess.run", return_value=fake_result),
            ):
                java_home = _validate_java_runtime()
                self.assertEqual(java_home.resolve(), (Path(temporary) / "env").resolve())

    def test_wait_tcp_fails_immediately_when_process_exits_early(self) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        managed = ManagedProcess(
            name="Cooja",
            process=mock_proc,
            log_path=Path("logs/cooja.log"),
            log_stream=MagicMock(),
        )
        with self.assertRaisesRegex(
            ExperimentError,
            r"Cooja exited with code 1 before TCP endpoint 127\.0\.0\.1:60001 became ready; see logs[/\\]cooja\.log",
        ):
            _wait_tcp("127.0.0.1", 60001, timeout_seconds=10, process=managed)

    def test_managed_process_stop_handles_running_and_stopped_processes(self) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 99999
        mock_stream = MagicMock()
        managed = ManagedProcess(
            name="Cooja",
            process=mock_proc,
            log_path=Path("logs/cooja.log"),
            log_stream=mock_stream,
        )
        with patch.object(os, "killpg", create=True) as mock_killpg:
            managed.stop()
            mock_killpg.assert_called_with(99999, signal.SIGTERM)
            mock_proc.wait.assert_called()
            mock_stream.close.assert_called()


if __name__ == "__main__":
    unittest.main()
