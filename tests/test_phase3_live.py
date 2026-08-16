from __future__ import annotations

from pathlib import Path
import unittest

from synthran.fiveg_ansible import InventoryHost, NetworkInventory
from synthran.phase3_live import _core_address, _render_manifest
from synthran.phase3_runtime import Phase3Scenario


class Phase3LiveContractTests(unittest.TestCase):
    def test_manifest_never_claims_reservation_or_network_deployment(self) -> None:
        scenario = Phase3Scenario(
            "phase3-01",
            "acceptance-20260815-05",
            "12.1.0.1",
        )
        manifest = _render_manifest(
            scenario,
            status="running",
            scenario_path=Path("scenario.json"),
        )
        self.assertEqual(manifest["reservation_action"], "none")
        self.assertEqual(manifest["network_deployment_action"], "none")
        self.assertEqual(manifest["network_run_id"], "acceptance-20260815-05")

    def test_core_address_comes_from_inventory_not_a_hardcoded_host(self) -> None:
        inventory = NetworkInventory(
            path=Path("generated.ini"),
            sha256="0" * 64,
            core_node=InventoryHost(
                "core-node",
                {"ansible_user": "root", "ansible_host": "192.0.2.10"},
            ),
            ran_node=InventoryHost(
                "ran-node",
                {"ansible_user": "root", "ansible_host": "192.0.2.11"},
            ),
            all_vars={"core": "open5gs", "ran": "srsRAN", "rru": "rfsim"},
        )
        self.assertEqual(_core_address(inventory), "192.0.2.10")


if __name__ == "__main__":
    unittest.main()
