from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.entrypoint import main as entrypoint_main
from synthran.live_preflight import CommandResult
from synthran.r2lab import (
    R2LabResourceError,
    R2LabSelection,
    build_plan,
    execute_prepare,
    execute_release,
    gateway_command,
    run_doctor,
)


class FakeRunner:
    def __init__(self, *, lease_ok: bool = True, ping_failures: int = 0) -> None:
        self.lease_ok = lease_ok
        self.ping_failures = ping_failures
        self.commands: list[tuple[str, ...]] = []
        self.ping_attempts = 0

    @staticmethod
    def remote(command: tuple[str, ...]) -> tuple[str, ...]:
        split = command.index("--")
        return command[split + 2 :]

    def __call__(self, command, timeout_seconds: int) -> CommandResult:
        value = tuple(command)
        self.commands.append(value)
        remote = self.remote(value)
        if remote == ("rhubarbe", "leases", "--check"):
            return CommandResult(0 if self.lease_ok else 1, "", "")
        if remote[:1] == ("ping",):
            self.ping_attempts += 1
            if self.ping_attempts <= self.ping_failures:
                return CommandResult(1, "", "")
        return CommandResult(0, "", "")

    @property
    def remote_commands(self) -> list[tuple[str, ...]]:
        return [self.remote(command) for command in self.commands]


class R2LabTests(unittest.TestCase):
    def test_selection_accepts_reviewed_radios_and_modes(self) -> None:
        mbim = R2LabSelection.build(
            slice_name="oulu_user", radio="n300", ue="qhat01"
        )
        qmi = R2LabSelection.build(
            slice_name="oulu_user", radio="n320", ue="qhat20"
        )
        qfit = R2LabSelection.build(
            slice_name="oulu_user", radio="n320", ue="qfit07"
        )
        self.assertEqual(("qhat", "mbim"), (mbim.ue_kind, mbim.ue_mode))
        self.assertEqual(("qhat", "qmi"), (qmi.ue_kind, qmi.ue_mode))
        self.assertEqual(("qfit", "mbim"), (qfit.ue_kind, qfit.ue_mode))

    def test_selection_rejects_unreviewed_resources_and_unsafe_slice(self) -> None:
        with self.assertRaises(R2LabResourceError):
            R2LabSelection.build(
                slice_name="unsafe user", radio="n300", ue="qhat01"
            )
        with self.assertRaises(R2LabResourceError):
            R2LabSelection.build(
                slice_name="oulu_user", radio="benetel1", ue="qhat01"
            )
        with self.assertRaises(R2LabResourceError):
            R2LabSelection.build(
                slice_name="oulu_user", radio="n300", ue="phone1"
            )

    def test_gateway_command_uses_batch_ssh_and_strict_host_keys(self) -> None:
        command = gateway_command("oulu_user", "rhubarbe", "leases", "--check")
        self.assertEqual("ssh", command[0])
        self.assertIn("BatchMode=yes", command)
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("oulu_user@faraday.inria.fr", command)
        self.assertNotIn("password", " ".join(command).lower())

    def test_plan_redacts_slice_and_forbids_global_cleanup(self) -> None:
        selection = R2LabSelection.build(
            slice_name="private_slice", radio="n300", ue="qhat01"
        )
        plan = build_plan(run_id="r2lab-test-01", selection=selection)
        rendered = plan.render(as_json=True)
        self.assertNotIn("private_slice", rendered)
        self.assertNotIn("all-off", rendered)
        self.assertNotIn("rhubarbe bye", rendered)
        payload = json.loads(rendered)
        self.assertEqual("reuse-active", payload["lease_action"])
        self.assertFalse(payload["safety"]["password_storage"])
        self.assertFalse(payload["safety"]["global_power_off"])

    def test_doctor_is_read_only_and_requires_active_lease(self) -> None:
        selection = R2LabSelection.build(
            slice_name="oulu_user", radio="n300", ue="qhat01"
        )
        runner = FakeRunner()
        report = run_doctor(selection=selection, runner=runner)
        self.assertTrue(report.ready)
        self.assertEqual(
            [("true",), ("rhubarbe", "leases", "--check")],
            runner.remote_commands,
        )

        denied = FakeRunner(lease_ok=False)
        report = run_doctor(selection=selection, runner=denied)
        self.assertFalse(report.ready)

    def test_prepare_checks_lease_before_every_mutation_and_claims_resources(self) -> None:
        selection = R2LabSelection.build(
            slice_name="oulu_user", radio="n300", ue="qhat01"
        )
        plan = build_plan(run_id="r2lab-test-02", selection=selection)
        runner = FakeRunner(ping_failures=1)
        waits: list[float] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "r2lab"
            result = execute_prepare(
                plan=plan,
                run_root=root,
                runner=runner,
                sleeper=waits.append,
                power_settle_seconds=20,
                reachability_attempts=3,
                reachability_delay_seconds=10,
            )
            self.assertEqual("ready", result.status)
            self.assertTrue((root / "active.json").is_file())
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("ready", manifest["status"])
            self.assertEqual("held", manifest["resource_claim"])
            self.assertNotIn("oulu_user", result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual([20, 10], waits)

        remote = runner.remote_commands
        expected = [
            ("rhubarbe", "leases", "--check"),
            ("rhubarbe", "leases", "--check"),
            ("rhubarbe", "pdu", "on", "n300"),
            ("rhubarbe", "leases", "--check"),
            ("rhubarbe", "pdu", "off", "qhat01"),
            ("rhubarbe", "leases", "--check"),
            ("rhubarbe", "pdu", "on", "qhat01"),
            ("ping", "-c", "1", "-W", "1", "qhat01"),
            ("ping", "-c", "1", "-W", "1", "qhat01"),
            ("rhubarbe", "leases", "--check"),
        ]
        self.assertEqual(expected, remote)
        self.assertFalse(any("all-off" in command for command in map(" ".join, remote)))
        self.assertFalse(any("bye" in command for command in map(" ".join, remote)))

    def test_prepare_fails_before_mutation_without_a_lease(self) -> None:
        selection = R2LabSelection.build(
            slice_name="oulu_user", radio="n300", ue="qhat01"
        )
        plan = build_plan(run_id="r2lab-test-03", selection=selection)
        runner = FakeRunner(lease_ok=False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "r2lab"
            with self.assertRaises(R2LabResourceError):
                execute_prepare(
                    plan=plan,
                    run_root=root,
                    runner=runner,
                    sleeper=lambda _: None,
                )
            self.assertFalse((root / "active.json").exists())
            manifest = json.loads(
                (root / plan.run_id / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual("failed", manifest["status"])
            self.assertEqual("lease-check", manifest["failure_stage"])
        self.assertEqual(
            [("rhubarbe", "leases", "--check")], runner.remote_commands
        )

    def test_qfit_prepare_uses_only_selected_qfit_commands(self) -> None:
        selection = R2LabSelection.build(
            slice_name="oulu_user", radio="n320", ue="qfit07"
        )
        plan = build_plan(run_id="r2lab-test-04", selection=selection)
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as directory:
            execute_prepare(
                plan=plan,
                run_root=Path(directory) / "r2lab",
                runner=runner,
                sleeper=lambda _: None,
                reachability_attempts=1,
            )
        remote = runner.remote_commands
        self.assertIn(("qfit", "off", "qfit07"), remote)
        self.assertIn(("qfit", "on", "qfit07"), remote)
        self.assertNotIn(("rhubarbe", "pdu", "off", "qfit07"), remote)

    def test_release_requires_exact_local_claim_and_powers_only_owned_pair(self) -> None:
        selection = R2LabSelection.build(
            slice_name="oulu_user", radio="n300", ue="qhat01"
        )
        plan = build_plan(run_id="r2lab-test-05", selection=selection)
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "r2lab"
            execute_prepare(
                plan=plan,
                run_root=root,
                runner=runner,
                sleeper=lambda _: None,
                reachability_attempts=1,
            )
            runner.commands.clear()
            result = execute_release(
                run_id=plan.run_id,
                slice_name="oulu_user",
                run_root=root,
                runner=runner,
            )
            self.assertEqual("released", result.status)
            self.assertFalse((root / "active.json").exists())
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("released", manifest["status"])
            self.assertEqual("released", manifest["resource_claim"])

        self.assertEqual(
            [
                ("rhubarbe", "leases", "--check"),
                ("rhubarbe", "pdu", "off", "qhat01"),
                ("rhubarbe", "leases", "--check"),
                ("rhubarbe", "pdu", "off", "n300"),
            ],
            runner.remote_commands,
        )
        joined = "\n".join(" ".join(command) for command in runner.remote_commands)
        self.assertNotIn("all-off", joined)
        self.assertNotIn("rhubarbe bye", joined)

    def test_release_refuses_wrong_slice_or_missing_claim(self) -> None:
        selection = R2LabSelection.build(
            slice_name="oulu_user", radio="n300", ue="qhat01"
        )
        plan = build_plan(run_id="r2lab-test-06", selection=selection)
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "r2lab"
            execute_prepare(
                plan=plan,
                run_root=root,
                runner=runner,
                sleeper=lambda _: None,
                reachability_attempts=1,
            )
            with self.assertRaises(R2LabResourceError):
                execute_release(
                    run_id=plan.run_id,
                    slice_name="other_user",
                    run_root=root,
                    runner=runner,
                )
            (root / "active.json").unlink()
            with self.assertRaises(R2LabResourceError):
                execute_release(
                    run_id=plan.run_id,
                    slice_name="oulu_user",
                    run_root=root,
                    runner=runner,
                )

    def test_failed_release_retains_claim_for_explicit_retry(self) -> None:
        selection = R2LabSelection.build(
            slice_name="oulu_user", radio="n300", ue="qhat01"
        )
        plan = build_plan(run_id="r2lab-test-07", selection=selection)
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "r2lab"
            execute_prepare(
                plan=plan,
                run_root=root,
                runner=runner,
                sleeper=lambda _: None,
                reachability_attempts=1,
            )

            class RadioOffFailure(FakeRunner):
                def __call__(self, command, timeout_seconds: int) -> CommandResult:
                    result = super().__call__(command, timeout_seconds)
                    if self.remote(tuple(command)) == (
                        "rhubarbe",
                        "pdu",
                        "off",
                        "n300",
                    ):
                        return CommandResult(1, "", "")
                    return result

            failing = RadioOffFailure()
            with self.assertRaises(R2LabResourceError):
                execute_release(
                    run_id=plan.run_id,
                    slice_name="oulu_user",
                    run_root=root,
                    runner=failing,
                )
            self.assertTrue((root / "active.json").is_file())
            manifest = json.loads(
                (root / plan.run_id / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual("release-failed", manifest["status"])
            self.assertEqual("held", manifest["resource_claim"])

    def test_run_id_is_never_reused(self) -> None:
        selection = R2LabSelection.build(
            slice_name="oulu_user", radio="n300", ue="qhat01"
        )
        plan = build_plan(run_id="r2lab-test-08", selection=selection)
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "r2lab"
            execute_prepare(
                plan=plan,
                run_root=root,
                runner=runner,
                sleeper=lambda _: None,
                reachability_attempts=1,
            )
            with self.assertRaises(R2LabResourceError):
                execute_prepare(
                    plan=plan,
                    run_root=root,
                    runner=runner,
                    sleeper=lambda _: None,
                    reachability_attempts=1,
                )

    def test_entrypoint_routes_only_r2lab_group_to_provider(self) -> None:
        with patch("synthran.entrypoint.r2lab_main", return_value=7) as r2lab:
            self.assertEqual(7, entrypoint_main(["r2lab", "doctor"]))
            r2lab.assert_called_once_with(["doctor"])
        with patch("synthran.entrypoint.core_main", return_value=9) as core:
            self.assertEqual(9, entrypoint_main(["doctor"]))
            core.assert_called_once_with(["doctor"])


if __name__ == "__main__":
    unittest.main()
