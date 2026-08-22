from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from synthran.r2lab.acceptance import (
    AcceptanceOutcome,
    PHYSICAL_RUN_EVIDENCE_SCHEMA,
    PhysicalAcceptance,
    PhysicalAcceptanceStage,
    PhysicalRunEvidence,
    R2LabAcceptanceError,
    STAGE_ORDER,
    StagedPhysicalEvidence,
)
from synthran.r2lab.radio import (
    CellAcquisitionState,
    Ipv4State,
    PacketServiceState,
    QfitRuntimeEvidence,
    RegistrationState,
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


class R2LabPersistentEvidenceTests(unittest.TestCase):
    def staging_payload(self, *, run_id: str = "r2lab-evidence") -> dict[str, object]:
        return {
            "run_id": run_id,
            "package_sha256": "a" * 64,
            "values_sha256": "b" * 64,
            "render_sha256": "c" * 64,
            "namespace_owned": True,
            "desired_replicas": 0,
            "gnb_pod_count": 0,
            "status": "staged-stopped",
            "hardware_mutation": False,
        }

    def prepared_for_qfit_runtime(self) -> PhysicalRunEvidence:
        evidence = PhysicalRunEvidence(run_id="r2lab-evidence").bind_staging(
            self.staging_payload()
        )
        for stage in STAGE_ORDER[:6]:
            evidence = evidence.pass_stage(stage, source=f"evidence-{stage.value}")
        return evidence

    def test_staging_digest_binds_exact_stopped_result(self) -> None:
        first = StagedPhysicalEvidence.from_staging_result(self.staging_payload())
        second = StagedPhysicalEvidence.from_staging_result(self.staging_payload())
        self.assertEqual(first.staging_sha256, second.staging_sha256)
        self.assertEqual(64, len(first.staging_sha256))

        changed = self.staging_payload()
        changed["render_sha256"] = "d" * 64
        third = StagedPhysicalEvidence.from_staging_result(changed)
        self.assertNotEqual(first.staging_sha256, third.staging_sha256)

    def test_unsafe_or_running_staging_result_is_not_persistable(self) -> None:
        running = self.staging_payload()
        running["desired_replicas"] = 1
        with self.assertRaisesRegex(R2LabAcceptanceError, "zero-pod"):
            StagedPhysicalEvidence.from_staging_result(running)

        mutated = self.staging_payload()
        mutated["hardware_mutation"] = True
        with self.assertRaisesRegex(R2LabAcceptanceError, "hardware mutation"):
            StagedPhysicalEvidence.from_staging_result(mutated)

    def test_run_evidence_binds_staging_once_and_preserves_ordered_acceptance(self) -> None:
        evidence = PhysicalRunEvidence(run_id="r2lab-evidence")
        evidence = evidence.bind_staging(self.staging_payload())
        evidence = evidence.pass_stage(
            PhysicalAcceptanceStage.RESOURCE_AUTHORITY,
            source="fresh-r2lab-and-slices-authority",
        )
        evidence = evidence.pass_stage(
            PhysicalAcceptanceStage.SLICES_FOUNDATION,
            source="owned-stopped-staging",
        )

        payload = evidence.to_dict()
        self.assertEqual(PHYSICAL_RUN_EVIDENCE_SCHEMA, payload["schema"])
        self.assertEqual("r2lab-evidence", payload["run_id"])
        self.assertEqual("staged-stopped", payload["staged"]["status"])
        self.assertEqual("passed", payload["acceptance"]["stages"][0]["outcome"])
        self.assertEqual("passed", payload["acceptance"]["stages"][1]["outcome"])
        self.assertEqual("kubernetes", payload["acceptance"]["next_stage"])

        with self.assertRaisesRegex(R2LabAcceptanceError, "immutable staging"):
            evidence.bind_staging(self.staging_payload())

    def test_run_id_mismatch_is_rejected(self) -> None:
        evidence = PhysicalRunEvidence(run_id="r2lab-evidence")
        with self.assertRaisesRegex(R2LabAcceptanceError, "different physical run"):
            evidence.bind_staging(self.staging_payload(run_id="r2lab-other"))

    def test_atomic_json_persistence_contains_hashes_and_acceptance(self) -> None:
        evidence = PhysicalRunEvidence(run_id="r2lab-evidence").bind_staging(
            self.staging_payload()
        )
        evidence = evidence.pass_stage(
            PhysicalAcceptanceStage.RESOURCE_AUTHORITY,
            source="authority-evidence",
        )

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "evidence" / "physical-run.json"
            written = evidence.write_json(target)
            self.assertEqual(target.resolve(), written)
            payload = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(PHYSICAL_RUN_EVIDENCE_SCHEMA, payload["schema"])
        self.assertEqual("a" * 64, payload["staged"]["package_sha256"])
        self.assertEqual("b" * 64, payload["staged"]["values_sha256"])
        self.assertEqual("c" * 64, payload["staged"]["render_sha256"])
        self.assertEqual(64, len(payload["staged"]["staging_sha256"]))
        self.assertEqual("passed", payload["acceptance"]["stages"][0]["outcome"])

    def test_no_service_qfit_runtime_records_cell_failure_only(self) -> None:
        evidence = self.prepared_for_qfit_runtime().record_qfit_runtime(
            QfitRuntimeEvidence(
                cell=CellAcquisitionState.NO_SERVICE,
                registration=RegistrationState.NOT_REGISTERED,
                packet_service=PacketServiceState.DETACHED,
                ipv4=Ipv4State.ABSENT,
            )
        )
        self.assertEqual(
            PhysicalAcceptanceStage.CELL_ACQUISITION,
            evidence.acceptance.failed_stage,
        )
        self.assertEqual(
            AcceptanceOutcome.NOT_REACHED,
            evidence.acceptance.outcome_for(PhysicalAcceptanceStage.REGISTRATION),
        )
        self.assertIn(
            "cell-no-service",
            evidence.to_dict()["acceptance"]["stages"][6]["source"],
        )

    def test_registered_attached_qfit_runtime_advances_through_pdu_only(self) -> None:
        evidence = self.prepared_for_qfit_runtime().record_qfit_runtime(
            QfitRuntimeEvidence(
                cell=CellAcquisitionState.ACQUIRED_NR_SA,
                registration=RegistrationState.REGISTERED,
                packet_service=PacketServiceState.ATTACHED,
                ipv4=Ipv4State.PRESENT,
            )
        )
        self.assertEqual(
            AcceptanceOutcome.PASSED,
            evidence.acceptance.outcome_for(PhysicalAcceptanceStage.CELL_ACQUISITION),
        )
        self.assertEqual(
            AcceptanceOutcome.PASSED,
            evidence.acceptance.outcome_for(PhysicalAcceptanceStage.REGISTRATION),
        )
        self.assertEqual(
            AcceptanceOutcome.PASSED,
            evidence.acceptance.outcome_for(PhysicalAcceptanceStage.PDU_SESSION),
        )
        self.assertEqual(
            AcceptanceOutcome.NOT_REACHED,
            evidence.acceptance.outcome_for(PhysicalAcceptanceStage.USER_PLANE),
        )
        self.assertEqual(
            PhysicalAcceptanceStage.USER_PLANE,
            evidence.acceptance.next_stage,
        )

    def test_qfit_runtime_cannot_skip_lower_acceptance_stages(self) -> None:
        evidence = PhysicalRunEvidence(run_id="r2lab-evidence").bind_staging(
            self.staging_payload()
        )
        with self.assertRaisesRegex(R2LabAcceptanceError, "requires cell-acquisition"):
            evidence.record_qfit_runtime(
                QfitRuntimeEvidence(
                    cell=CellAcquisitionState.ACQUIRED_NR_SA,
                    registration=RegistrationState.REGISTERED,
                    packet_service=PacketServiceState.ATTACHED,
                    ipv4=Ipv4State.PRESENT,
                )
            )


if __name__ == "__main__":
    unittest.main()
