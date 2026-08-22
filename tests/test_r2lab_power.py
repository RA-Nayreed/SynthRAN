from __future__ import annotations

import unittest

from synthran.network.r2lab_power import (
    PowerState,
    R2LabPowerStateError,
    evaluate_pdu_transition,
    parse_pdu_status,
)


class R2LabPowerStateTests(unittest.TestCase):
    def test_parses_exact_on_state_and_watts(self) -> None:
        observation = parse_pdu_status(
            "pdu2 chain-0@outlet-1 (n300): ON (28W)\n",
            resource="n300",
        )
        self.assertEqual(PowerState.ON, observation.state)
        self.assertEqual(28, observation.watts)

    def test_parses_exact_off_state_without_watts(self) -> None:
        observation = parse_pdu_status(
            "pdu2 chain-0@outlet-1 (n300): OFF\n",
            resource="n300",
        )
        self.assertEqual(PowerState.OFF, observation.state)
        self.assertIsNone(observation.watts)

    def test_ignores_other_resources(self) -> None:
        observation = parse_pdu_status(
            "pdu2 chain-0@outlet-1 (n320): OFF\n",
            resource="n300",
        )
        self.assertEqual(PowerState.UNKNOWN, observation.state)

    def test_conflicting_state_fails_closed(self) -> None:
        with self.assertRaises(R2LabPowerStateError):
            parse_pdu_status(
                "\n".join(
                    (
                        "pdu2 chain-0@outlet-1 (n300): ON (28W)",
                        "pdu2 chain-0@outlet-1 (n300): OFF",
                    )
                ),
                resource="n300",
            )

    def test_successful_off_does_not_require_zero_mutation_returncode(self) -> None:
        evidence = evaluate_pdu_transition(
            resource="n300",
            requested_state=PowerState.OFF,
            mutation_returncode=1,
            status_returncode=0,
            status_stdout="pdu2 chain-0@outlet-1 (n300): OFF\n",
        )
        self.assertTrue(evidence.confirmed)
        self.assertEqual(1, evidence.mutation_returncode)
        self.assertEqual(PowerState.OFF, evidence.observed_state)

    def test_timeout_returncode_can_still_be_resolved_by_exact_status(self) -> None:
        evidence = evaluate_pdu_transition(
            resource="n300",
            requested_state=PowerState.OFF,
            mutation_returncode=None,
            status_returncode=0,
            status_stdout="pdu2 chain-0@outlet-1 (n300): OFF\n",
        )
        self.assertTrue(evidence.confirmed)
        self.assertIsNone(evidence.mutation_returncode)

    def test_timeout_without_state_evidence_remains_unknown(self) -> None:
        evidence = evaluate_pdu_transition(
            resource="n300",
            requested_state=PowerState.OFF,
            mutation_returncode=None,
            status_returncode=None,
        )
        self.assertFalse(evidence.confirmed)
        self.assertEqual(PowerState.UNKNOWN, evidence.observed_state)

    def test_textual_state_not_mutation_returncode_decides_transition(self) -> None:
        evidence = evaluate_pdu_transition(
            resource="n300",
            requested_state=PowerState.OFF,
            mutation_returncode=0,
            status_returncode=0,
            status_stdout="pdu2 chain-0@outlet-1 (n300): ON (28W)\n",
        )
        self.assertFalse(evidence.confirmed)
        self.assertEqual(PowerState.ON, evidence.observed_state)

    def test_status_text_can_be_read_from_stderr(self) -> None:
        evidence = evaluate_pdu_transition(
            resource="n300",
            requested_state=PowerState.OFF,
            mutation_returncode=1,
            status_returncode=1,
            status_stderr="pdu2 chain-0@outlet-1 (n300): OFF\n",
        )
        self.assertTrue(evidence.confirmed)

    def test_missing_status_text_remains_unknown(self) -> None:
        evidence = evaluate_pdu_transition(
            resource="n300",
            requested_state=PowerState.OFF,
            mutation_returncode=0,
            status_returncode=0,
        )
        self.assertFalse(evidence.confirmed)
        self.assertEqual(PowerState.UNKNOWN, evidence.observed_state)

    def test_unknown_is_not_a_valid_requested_state(self) -> None:
        with self.assertRaises(R2LabPowerStateError):
            evaluate_pdu_transition(
                resource="n300",
                requested_state=PowerState.UNKNOWN,
                mutation_returncode=0,
                status_returncode=0,
                status_stdout="pdu2 chain-0@outlet-1 (n300): OFF\n",
            )


if __name__ == "__main__":
    unittest.main()
