from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.experiment import ExperimentError, ExperimentScenario
from synthran.experiment_runtime import (
    _core_address,
    _discover_ue_deployment,
    _discover_ue_pod,
    _one_name,
    _prepare_cooja_checkout,
    _render_manifest,
)
from synthran.fiveg_ansible import InventoryHost, NetworkInventory, load_inventory
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


if __name__ == "__main__":
    unittest.main()
