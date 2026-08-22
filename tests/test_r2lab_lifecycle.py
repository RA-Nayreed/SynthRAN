from __future__ import annotations

import unittest

from synthran.r2lab.provider import (
    CleanupEvidence,
    CleanupState,
    release_assessment,
)


class R2LabLifecycleTests(unittest.TestCase):
    def test_claim_releases_only_when_both_exact_resources_are_proven_off(self) -> None:
        assessment = release_assessment(
            ue=CleanupEvidence(
                resource="qfit07",
                stage="ue-power-off-release",
                state=CleanupState.PROVEN_OFF,
                source="provider-status",
            ),
            radio=CleanupEvidence(
                resource="n300",
                stage="radio-power-off-release",
                state=CleanupState.PROVEN_OFF,
                source="pdu-status",
            ),
        )
        self.assertTrue(assessment.claim_releasable)
        self.assertEqual((), assessment.unresolved_resources)

    def test_unknown_ue_keeps_claim_even_when_radio_is_clean(self) -> None:
        assessment = release_assessment(
            ue=CleanupEvidence(
                resource="qfit07",
                stage="ue-power-off-release",
                state=CleanupState.UNKNOWN,
                source="timeout",
            ),
            radio=CleanupEvidence(
                resource="n300",
                stage="radio-power-off-release",
                state=CleanupState.PROVEN_OFF,
                source="pdu-status",
            ),
        )
        self.assertFalse(assessment.claim_releasable)
        self.assertEqual(("qfit07",), assessment.unresolved_resources)

    def test_unknown_radio_keeps_claim_even_when_ue_is_clean(self) -> None:
        assessment = release_assessment(
            ue=CleanupEvidence(
                resource="qfit07",
                stage="ue-power-off-release",
                state=CleanupState.PROVEN_OFF,
                source="provider-status",
            ),
            radio=CleanupEvidence(
                resource="n300",
                stage="radio-power-off-release",
                state=CleanupState.UNKNOWN,
                source="missing-status",
            ),
        )
        self.assertFalse(assessment.claim_releasable)
        self.assertEqual(("n300",), assessment.unresolved_resources)

    def test_proven_on_is_not_clean(self) -> None:
        assessment = release_assessment(
            ue=CleanupEvidence(
                resource="qfit07",
                stage="ue-power-off-release",
                state=CleanupState.PROVEN_ON,
                source="provider-status",
            ),
            radio=CleanupEvidence(
                resource="n300",
                stage="radio-power-off-release",
                state=CleanupState.PROVEN_OFF,
                source="pdu-status",
            ),
        )
        self.assertFalse(assessment.claim_releasable)
        self.assertEqual(("qfit07",), assessment.unresolved_resources)

    def test_serialized_assessment_contains_only_sanitized_state(self) -> None:
        assessment = release_assessment(
            ue=CleanupEvidence(
                resource="qfit07",
                stage="ue-power-off-release",
                state=CleanupState.UNKNOWN,
                source="timeout",
            ),
            radio=CleanupEvidence(
                resource="n300",
                stage="radio-power-off-release",
                state=CleanupState.PROVEN_OFF,
                source="pdu-status",
            ),
        )
        payload = assessment.to_dict()
        self.assertFalse(payload["claim_releasable"])
        self.assertEqual(["qfit07"], payload["unresolved_resources"])
        self.assertEqual(2, len(payload["evidence"]))


if __name__ == "__main__":
    unittest.main()
