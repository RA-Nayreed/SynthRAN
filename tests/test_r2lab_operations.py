from __future__ import annotations

import unittest

from synthran.live_preflight import CommandResult
from synthran.r2lab.provider import PowerState, execute_verified_pdu_transition


class ScriptedRunner:
    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command, timeout_seconds: int) -> CommandResult:
        self.commands.append(tuple(command))
        outcome = self.script.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, CommandResult)
        return outcome


class R2LabVerifiedOperationTests(unittest.TestCase):
    def test_successful_off_accepts_live_rc1_semantics(self) -> None:
        runner = ScriptedRunner(
            [
                CommandResult(
                    1,
                    "Doing a soft TURN OFF on device n300\n"
                    "pdu2 chain-0@outlet-1 (n300): OFF\n",
                    "",
                ),
                CommandResult(0, "pdu2 chain-0@outlet-1 (n300): OFF\n", ""),
            ]
        )
        result = execute_verified_pdu_transition(
            resource="n300",
            requested_state=PowerState.OFF,
            runner=runner,
            timeout_seconds=30,
        )
        self.assertTrue(result.confirmed)
        self.assertEqual(1, result.evidence.mutation_returncode)
        self.assertEqual(PowerState.OFF, result.evidence.observed_state)
        self.assertEqual(
            [
                ("rhubarbe", "pdu", "off", "n300"),
                ("rhubarbe", "pdu", "status", "n300"),
            ],
            runner.commands,
        )

    def test_mutation_timeout_still_checks_exact_provider_state(self) -> None:
        runner = ScriptedRunner(
            [
                RuntimeError("timed out"),
                CommandResult(0, "pdu2 chain-0@outlet-1 (n300): OFF\n", ""),
            ]
        )
        result = execute_verified_pdu_transition(
            resource="n300",
            requested_state=PowerState.OFF,
            runner=runner,
            timeout_seconds=30,
        )
        self.assertTrue(result.confirmed)
        self.assertTrue(result.mutation_transport_error)
        self.assertIsNone(result.evidence.mutation_returncode)
        self.assertEqual(2, len(runner.commands))

    def test_status_timeout_keeps_transition_unresolved(self) -> None:
        runner = ScriptedRunner(
            [
                CommandResult(0, "", ""),
                RuntimeError("status timed out"),
            ]
        )
        result = execute_verified_pdu_transition(
            resource="n300",
            requested_state=PowerState.OFF,
            runner=runner,
            timeout_seconds=30,
        )
        self.assertFalse(result.confirmed)
        self.assertTrue(result.status_transport_error)
        self.assertEqual(PowerState.UNKNOWN, result.evidence.observed_state)

    def test_wrong_observed_state_is_not_confirmed(self) -> None:
        runner = ScriptedRunner(
            [
                CommandResult(0, "", ""),
                CommandResult(0, "pdu2 chain-0@outlet-1 (n300): ON (28W)\n", ""),
            ]
        )
        result = execute_verified_pdu_transition(
            resource="n300",
            requested_state=PowerState.OFF,
            runner=runner,
            timeout_seconds=30,
        )
        self.assertFalse(result.confirmed)
        self.assertEqual(PowerState.ON, result.evidence.observed_state)

    def test_status_returncode_is_diagnostic_when_text_is_exact(self) -> None:
        runner = ScriptedRunner(
            [
                CommandResult(0, "", ""),
                CommandResult(1, "", "pdu2 chain-0@outlet-1 (n300): OFF\n"),
            ]
        )
        result = execute_verified_pdu_transition(
            resource="n300",
            requested_state=PowerState.OFF,
            runner=runner,
            timeout_seconds=30,
        )
        self.assertTrue(result.confirmed)
        self.assertEqual(1, result.evidence.status_returncode)

    def test_on_transition_uses_only_exact_selected_resource(self) -> None:
        runner = ScriptedRunner(
            [
                CommandResult(0, "", ""),
                CommandResult(0, "pdu2 chain-0@outlet-1 (n320): ON (31W)\n", ""),
            ]
        )
        result = execute_verified_pdu_transition(
            resource="n320",
            requested_state=PowerState.ON,
            runner=runner,
            timeout_seconds=30,
        )
        self.assertTrue(result.confirmed)
        joined = "\n".join(" ".join(command) for command in runner.commands)
        self.assertNotIn("all-off", joined)
        self.assertNotIn("bye", joined)
        self.assertNotIn("n300", joined)


if __name__ == "__main__":
    unittest.main()
