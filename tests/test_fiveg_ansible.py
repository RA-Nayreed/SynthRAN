from __future__ import annotations

import json
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.dependencies import load_lock
from synthran.cli import _parser, main
from synthran.fiveg_ansible import (
    FiveGAnsibleError,
    PLAN_SCHEMA,
    build_network_plan,
    load_inventory,
    parse_inventory,
    run_offline_doctor,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "inventory_open5gs_srsran_rfsim.ini"


class InventoryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = FIXTURE.read_text(encoding="utf-8")

    def test_accepts_the_initial_golden_path(self) -> None:
        inventory = parse_inventory(self.text, source=Path("hosts.ini"))
        self.assertEqual("open5gs", inventory.core)
        self.assertEqual("srsRAN", inventory.ran)
        self.assertEqual("rfsim", inventory.radio)
        self.assertEqual("lab-core", inventory.core_node.name)
        self.assertEqual("lab-ran", inventory.ran_node.name)
        self.assertNotIn("ip", inventory.redacted_summary())
        self.assertNotIn("ansible_user", inventory.redacted_summary())

    def test_rejects_an_unsupported_core(self) -> None:
        text = self.text.replace('core="open5gs"', 'core="oai"')
        with self.assertRaisesRegex(FiveGAnsibleError, "only core=open5gs"):
            parse_inventory(text, source=Path("hosts.ini"))

    def test_rejects_an_unsupported_radio(self) -> None:
        text = self.text.replace('rru="rfsim"', 'rru="n300"')
        with self.assertRaisesRegex(FiveGAnsibleError, "only rru=rfsim"):
            parse_inventory(text, source=Path("hosts.ini"))

    def test_rejects_monitoring_in_the_initial_path(self) -> None:
        text = self.text.replace("monitoring_enabled=false", "monitoring_enabled=true")
        with self.assertRaisesRegex(FiveGAnsibleError, "must be false"):
            parse_inventory(text, source=Path("hosts.ini"))

    def test_rejects_mismatched_node_alias(self) -> None:
        text = self.text.replace('ran_node_name="lab-ran"', 'ran_node_name="other"')
        with self.assertRaisesRegex(FiveGAnsibleError, "ran_node_name must match"):
            parse_inventory(text, source=Path("hosts.ini"))

    def test_preserves_hash_characters_in_all_vars(self) -> None:
        text = self.text + "dpdk_interface_c=eth1#0-1\n"
        inventory = parse_inventory(text, source=Path("hosts.ini"))
        self.assertEqual("eth1#0-1", inventory.all_vars["dpdk_interface_c"])


class DeploymentPlanTests(unittest.TestCase):
    def test_live_commands_accept_preparation_authority_environment(self) -> None:
        authority = {
            "SYNTHRAN_OWNER": "operator",
            "SYNTHRAN_RESERVATION_ID": "7000000001",
            "SYNTHRAN_ALLOCATION_ID": "allocation-pair",
        }
        with patch.dict("os.environ", authority, clear=False):
            doctor = _parser().parse_args(
                ["doctor", "--inventory", str(FIXTURE)]
            )
            deploy = _parser().parse_args(
                ["network", "deploy", "--inventory", str(FIXTURE)]
            )
            prepare = _parser().parse_args(
                ["network", "prepare", "--run-id", "prepare-001"]
            )
        for args in (doctor, deploy):
            self.assertEqual("operator", args.owner)
            self.assertEqual("7000000001", args.reservation_id)
            self.assertEqual("allocation-pair", args.allocation_id)
        self.assertEqual("operator", prepare.owner)
        self.assertEqual("7000000001", prepare.reservation_id)

    def test_plan_uses_every_locked_deployment_commit(self) -> None:
        lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        inventory = load_inventory(FIXTURE)
        plan = build_network_plan(lock=lock, inventory=inventory, profile="default")
        data = plan.to_dict()
        self.assertEqual(PLAN_SCHEMA, data["schema"])
        self.assertFalse(data["execution_enabled"])
        self.assertEqual("none", data["reservation_action"])
        for name in ("fiveg_ansible", "open5gs_k8s", "srsran_helm"):
            self.assertEqual(lock.raw["git"][name]["commit"], data["dependencies"][name])
        playbook_command = data["commands"][-1]
        self.assertIn(
            f"repo_branch={lock.raw['git']['open5gs_k8s']['commit']}",
            playbook_command,
        )
        self.assertIn(
            f"version={lock.raw['git']['srsran_helm']['commit']}",
            playbook_command,
        )

    def test_json_plan_does_not_disclose_the_inventory_directory(self) -> None:
        lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        source = Path("private") / "operator" / "hosts.ini"
        inventory = parse_inventory(FIXTURE.read_text(encoding="utf-8"), source=source)
        plan = build_network_plan(lock=lock, inventory=inventory, profile="default")
        rendered = plan.render(as_json=True)
        self.assertNotIn("private", rendered)
        self.assertNotIn("operator", rendered)
        self.assertIn("hosts.ini", rendered)
        json.loads(rendered)

    def test_profile_cannot_inject_arguments(self) -> None:
        lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        inventory = load_inventory(FIXTURE)
        with self.assertRaisesRegex(FiveGAnsibleError, "may contain only"):
            build_network_plan(
                lock=lock,
                inventory=inventory,
                profile="default -e unsafe=true",
            )

    def test_offline_doctor_fails_without_the_locked_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = run_offline_doctor(
                inventory_path=FIXTURE,
                lock_path=REPOSITORY_ROOT / "dependencies.lock.yml",
                dependency_root=Path(directory),
            )
        self.assertFalse(report.ready)
        failed = {check.name: check.detail for check in report.checks if not check.passed}
        self.assertIn("fiveg-ansible", failed)
        self.assertNotIn(directory, report.render())

    def test_cli_requires_every_live_deployment_gate(self) -> None:
        stderr = StringIO()
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(stderr):
            result = main(
                [
                    "network",
                    "deploy",
                    "--inventory",
                    str(FIXTURE),
                    "--deps-root",
                    directory,
                ]
            )
        self.assertEqual(2, result)
        self.assertIn(
            "live deployment requires --slices-project, --slices-experiment, --owner, "
            "--reservation-id, --allocation-id, "
            "--preflight-evidence, --run-id",
            stderr.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
