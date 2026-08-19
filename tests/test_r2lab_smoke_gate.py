from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from synthran.fiveg_ansible import load_inventory
from synthran.live_preflight import CommandResult
from synthran.network.r2lab import (
    R2LabSelection,
    build_plan,
    execute_prepare,
    execute_release,
    run_doctor,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RFSIM_FIXTURE = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "inventory_open5gs_srsran_rfsim.ini"
)


class SmokeRunner:
    """Deterministic provider double for the complete public smoke lifecycle."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    @staticmethod
    def remote(command: tuple[str, ...]) -> tuple[str, ...]:
        split = command.index("--")
        return command[split + 2 :]

    def __call__(self, command, timeout_seconds: int) -> CommandResult:
        value = tuple(command)
        self.commands.append(value)
        remote = self.remote(value)
        if remote in {
            ("true",),
            ("rhubarbe", "leases", "--check"),
        }:
            return CommandResult(0, "", "")
        if remote[:1] == ("ping",):
            return CommandResult(0, "", "")
        return CommandResult(0, "", "")

    @property
    def remote_commands(self) -> list[tuple[str, ...]]:
        return [self.remote(command) for command in self.commands]


class R2LabSmokeGateTests(unittest.TestCase):
    def test_current_rfsim_golden_path_remains_the_regression_baseline(self) -> None:
        inventory = load_inventory(RFSIM_FIXTURE)
        self.assertEqual("open5gs", inventory.core)
        self.assertEqual("srsRAN", inventory.ran)
        self.assertEqual("rfsim", inventory.radio)

    def test_complete_r2lab_resource_smoke_cycle_is_exact_and_released(self) -> None:
        selection = R2LabSelection.build(
            slice_name="oulu_user",
            radio="n300",
            ue="qhat01",
        )
        runner = SmokeRunner()

        doctor = run_doctor(selection=selection, runner=runner)
        self.assertTrue(doctor.ready)
        self.assertEqual(
            [("true",), ("rhubarbe", "leases", "--check")],
            runner.remote_commands,
        )

        plan = build_plan(run_id="r2lab-smoke-001", selection=selection)
        payload = plan.to_dict()
        rendered = plan.render(as_json=True)
        self.assertFalse(payload["execution_enabled"])
        self.assertEqual("reuse-active", payload["lease_action"])
        self.assertFalse(payload["safety"]["automatic_lease_booking"])
        self.assertFalse(payload["safety"]["password_storage"])
        self.assertFalse(payload["safety"]["global_power_off"])
        self.assertNotIn("oulu_user", rendered)
        self.assertNotIn("all-off", rendered)
        self.assertNotIn("password", rendered.lower())

        runner.commands.clear()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "r2lab"
            prepared = execute_prepare(
                plan=plan,
                run_root=root,
                runner=runner,
                sleeper=lambda _: None,
                reachability_attempts=1,
            )
            self.assertEqual("ready", prepared.status)
            self.assertTrue((root / "active.json").is_file())

            ready_manifest = json.loads(
                prepared.manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual("ready", ready_manifest["status"])
            self.assertEqual("held", ready_manifest["resource_claim"])
            self.assertNotIn(
                "oulu_user",
                prepared.manifest_path.read_text(encoding="utf-8"),
            )

            prepare_commands = runner.remote_commands
            self.assertEqual(
                [
                    ("rhubarbe", "leases", "--check"),
                    ("rhubarbe", "leases", "--check"),
                    ("rhubarbe", "pdu", "on", "n300"),
                    ("rhubarbe", "leases", "--check"),
                    ("rhubarbe", "pdu", "off", "qhat01"),
                    ("rhubarbe", "leases", "--check"),
                    ("rhubarbe", "pdu", "on", "qhat01"),
                    ("ping", "-c", "1", "-W", "1", "qhat01"),
                    ("rhubarbe", "leases", "--check"),
                ],
                prepare_commands,
            )

            runner.commands.clear()
            released = execute_release(
                run_id=plan.run_id,
                slice_name="oulu_user",
                run_root=root,
                runner=runner,
            )
            self.assertEqual("released", released.status)
            self.assertFalse((root / "active.json").exists())

            released_manifest = json.loads(
                released.manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual("released", released_manifest["status"])
            self.assertEqual("released", released_manifest["resource_claim"])

            self.assertEqual(
                [
                    ("rhubarbe", "leases", "--check"),
                    ("rhubarbe", "pdu", "off", "qhat01"),
                    ("rhubarbe", "leases", "--check"),
                    ("rhubarbe", "pdu", "off", "n300"),
                ],
                runner.remote_commands,
            )

        all_commands = "\n".join(
            " ".join(command) for command in prepare_commands + runner.remote_commands
        )
        self.assertNotIn("all-off", all_commands)
        self.assertNotIn("rhubarbe bye", all_commands)
        self.assertNotIn("password", all_commands.lower())


if __name__ == "__main__":
    unittest.main()
