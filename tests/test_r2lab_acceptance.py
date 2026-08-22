from __future__ import annotations

import unittest

from synthran.r2lab.acceptance import (
    AcceptanceOutcome,
    PhysicalAcceptance,
    PhysicalAcceptanceStage,
    R2LabAcceptanceError,
    STAGE_ORDER,
)


class R2LabAcceptanceTests(unittest.TestCase):
    def test_stages_cannot_be_skipped(self) -> None:
        state = PhysicalAcceptance()
        with self.assertRaisesRegex(R2LabAcceptanceError, "next physical acceptance stage"):
            state.pass_stage(
                PhysicalAcceptanceStage.OPEN5GS,
                source="core-ready",
            )

    def test_failed_cell_acquisition_blocks_later_acceptance(self) -> None:
        state = PhysicalAcceptance()
        for stage in STAGE_ORDER[:6]:
            state = state.pass_stage(stage, source=f"evidence-{stage.value}")
        state = state.fail_stage(
            PhysicalAcceptanceStage.CELL_ACQUISITION,
            source="qfit-no-service-zero-scan-results",
        )

        self.assertFalse(state.accepted)
        self.assertEqual(
            PhysicalAcceptanceStage.CELL_ACQUISITION,
            state.failed_stage,
        )
        self.assertEqual(
            AcceptanceOutcome.NOT_REACHED,
            state.outcome_for(PhysicalAcceptanceStage.REGISTRATION),
        )
        with self.assertRaisesRegex(R2LabAcceptanceError, "blocked by failure"):
            state.pass_stage(
                PhysicalAcceptanceStage.REGISTRATION,
                source="must-not-be-accepted",
            )

    def test_complete_chain_is_required_for_backend_acceptance(self) -> None:
        state = PhysicalAcceptance()
        for stage in STAGE_ORDER:
            state = state.pass_stage(stage, source=f"evidence-{stage.value}")

        self.assertTrue(state.accepted)
        self.assertIsNone(state.next_stage)
        payload = state.to_dict()
        self.assertTrue(payload["accepted"])
        self.assertIsNone(payload["failed_stage"])
        self.assertEqual("passed", payload["stages"][-1]["outcome"])

    def test_not_reached_is_derived_not_recorded(self) -> None:
        state = PhysicalAcceptance()
        with self.assertRaisesRegex(R2LabAcceptanceError, "derived state"):
            state.record(
                stage=PhysicalAcceptanceStage.RESOURCE_AUTHORITY,
                outcome=AcceptanceOutcome.NOT_REACHED,
                source="none",
            )

    def test_summary_keeps_unreached_stages_explicit(self) -> None:
        state = PhysicalAcceptance().pass_stage(
            PhysicalAcceptanceStage.RESOURCE_AUTHORITY,
            source="active-lease",
        )
        payload = state.to_dict()
        self.assertEqual(
            PhysicalAcceptanceStage.SLICES_FOUNDATION.value,
            payload["next_stage"],
        )
        self.assertEqual("passed", payload["stages"][0]["outcome"])
        self.assertEqual("not-reached", payload["stages"][1]["outcome"])
        self.assertIsNone(payload["stages"][1]["source"])


if __name__ == "__main__":
    unittest.main()
