from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from synthran.experiment import ExperimentError, ExperimentScenario
from synthran.experiment_runtime import _core_address, _render_manifest
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


if __name__ == "__main__":
    unittest.main()
