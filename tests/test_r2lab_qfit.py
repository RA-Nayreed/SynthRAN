from __future__ import annotations

import unittest

from synthran.live_preflight import CommandResult
from synthran.r2lab.provider import (
    PowerState,
    R2LabQfitStateError,
    execute_verified_qfit_transition,
    parse_qfit_status,
    qfit_node_number,
)


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


class R2LabQfitTests(unittest.TestCase):
    def test_qfit_identifier_maps_to_exact_r2lab_node(self) -> None:
        self.assertEqual(7, qfit_node_number("qfit07"))
        self.assertEqual(34, qfit_node_number("qfit34"))

    def test_invalid_qfit_identifier_fails_closed(self) -> None:
        for value in ("fit07", "qfit7", "qfit00", "qfit07;all-off"):
            with self.subTest(value=value):
                with self.assertRaises(R2LabQfitStateError):
                    qfit_node_number(value)

    def test_parses_exact_live_off_observation(self) -> None:
        observation = parse_qfit_status("reboot07:off\n", qfit="qfit07")
        self.assertEqual(7, observation.node)
        self.assertEqual(PowerState.OFF, observation.state)

    def test_other_reboot_node_is_ignored(self) -> None:
        observation = parse_qfit_status("reboot09:off\n", qfit="qfit07")
        self.assertEqual(PowerState.UNKNOWN, observation.state)

    def test_conflicting_qfit_status_fails_closed(self) -> None:
        with self.assertRaises(R2LabQfitStateError):
            parse_qfit_status("reboot07:on\nreboot07:off\n", qfit="qfit07")

    def test_verified_off_uses_qfit_then_exact_status_node(self) -> None:
        runner = ScriptedRunner(
            [
                CommandResult(0, "reboot07:ok\n", ""),
                CommandResult(0, "reboot07:off\n", ""),
            ]
        )
        result = execute_verified_qfit_transition(
            qfit="qfit07",
            requested_state=PowerState.OFF,
            runner=runner,
            timeout_seconds=30,
        )
        self.assertTrue(result.confirmed)
        self.assertEqual(
            [("qfit", "off", "qfit07"), ("rhubarbe", "status", "7")],
            runner.commands,
        )

    def test_qfit_mutation_timeout_still_queries_exact_status(self) -> None:
        runner = ScriptedRunner(
            [
                RuntimeError("qfit timed out"),
                CommandResult(0, "reboot07:off\n", ""),
            ]
        )
        result = execute_verified_qfit_transition(
            qfit="qfit07",
            requested_state=PowerState.OFF,
            runner=runner,
            timeout_seconds=30,
        )
        self.assertTrue(result.confirmed)
        self.assertTrue(result.mutation_transport_error)
        self.assertEqual(2, len(runner.commands))

    def test_qfit_status_timeout_is_unresolved(self) -> None:
        runner = ScriptedRunner(
            [
                CommandResult(0, "", ""),
                RuntimeError("status timed out"),
            ]
        )
        result = execute_verified_qfit_transition(
            qfit="qfit07",
            requested_state=PowerState.OFF,
            runner=runner,
            timeout_seconds=30,
        )
        self.assertFalse(result.confirmed)
        self.assertEqual(PowerState.UNKNOWN, result.observed_state)
        self.assertTrue(result.status_transport_error)

    def test_qfit_on_requires_provider_to_report_on(self) -> None:
        runner = ScriptedRunner(
            [
                CommandResult(0, "", ""),
                CommandResult(0, "reboot07:off\n", ""),
            ]
        )
        result = execute_verified_qfit_transition(
            qfit="qfit07",
            requested_state=PowerState.ON,
            runner=runner,
            timeout_seconds=30,
        )
        self.assertFalse(result.confirmed)
        self.assertEqual(PowerState.OFF, result.observed_state)


if __name__ == "__main__":
    unittest.main()
