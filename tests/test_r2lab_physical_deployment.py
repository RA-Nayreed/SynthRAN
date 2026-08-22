from __future__ import annotations

import unittest

from synthran.network.r2lab_physical_deployment import (
    R2LabPhysicalDeploymentError,
    build_physical_deployment_plan,
)


class R2LabPhysicalDeploymentTests(unittest.TestCase):
    def test_plan_is_separate_nonexecuting_r2lab_boundary(self) -> None:
        plan = build_physical_deployment_plan(run_id="r2lab-physical-plan")
        payload = plan.to_dict()

        self.assertFalse(payload["execution_enabled"])
        self.assertEqual("offline-plan-only", payload["acceptance"])
        self.assertEqual("r2lab", payload["backend"])
        self.assertEqual("open5gs", payload["core"])
        self.assertEqual("srsran", payload["ran"])
        self.assertEqual("n300", payload["radio"])
        self.assertEqual("Recreate", payload["deployment"]["strategy"])
        self.assertEqual(1, payload["deployment"]["max_concurrent_gnb_pods"])
        self.assertFalse(payload["deployment"]["srsue_specific_overrides"])
        self.assertIsNone(payload["deployment"]["coreset0_index_override"])
        self.assertIsNone(payload["deployment"]["prach_config_index_override"])
        self.assertFalse(payload["safety"]["rolling_overlap_allowed"])
        self.assertFalse(payload["safety"]["virtual_adapter_modified"])
        self.assertFalse(payload["safety"]["live_acceptance_claimed"])

    def test_reference_aligned_plan_uses_distinct_carrier_and_ssb(self) -> None:
        payload = build_physical_deployment_plan(
            run_id="r2lab-physical-frequency"
        ).to_dict()
        intent = payload["radio_intent"]
        carrier = intent["profile"]["carrier"]
        ssb = intent["expected_ssb"]

        self.assertEqual(621_984, carrier["arfcn"])
        self.assertEqual("carrier-center", carrier["semantic"])
        self.assertEqual(621_312, ssb["arfcn"])
        self.assertEqual("ssb", ssb["semantic"])
        self.assertNotEqual(carrier["arfcn"], ssb["arfcn"])
        self.assertEqual(60, intent["profile"]["channel_bandwidth_mhz"])
        self.assertEqual(2, intent["profile"]["nof_antennas_dl"])
        self.assertEqual(2, intent["profile"]["nof_antennas_ul"])

    def test_render_never_claims_live_acceptance(self) -> None:
        rendered = build_physical_deployment_plan(
            run_id="r2lab-physical-render"
        ).render()
        self.assertIn("NON-EXECUTING", rendered)
        self.assertIn("not live accepted", rendered)
        self.assertIn("Recreate", rendered)
        self.assertNotIn("RFSIM", rendered.upper())

    def test_virtual_or_unreviewed_topology_is_rejected(self) -> None:
        with self.assertRaises(R2LabPhysicalDeploymentError):
            build_physical_deployment_plan(
                run_id="r2lab-bad-radio",
                radio="rfsim",
            )
        with self.assertRaises(R2LabPhysicalDeploymentError):
            build_physical_deployment_plan(
                run_id="r2lab-bad-core",
                core_node="sopnode-f1",
            )
        with self.assertRaises(R2LabPhysicalDeploymentError):
            build_physical_deployment_plan(
                run_id="r2lab-bad-ran",
                ran_node="sopnode-w3",
            )

    def test_gain_boundary_is_fail_closed(self) -> None:
        with self.assertRaises(R2LabPhysicalDeploymentError):
            build_physical_deployment_plan(
                run_id="r2lab-high-tx",
                tx_gain_db=31,
            )
        with self.assertRaises(R2LabPhysicalDeploymentError):
            build_physical_deployment_plan(
                run_id="r2lab-high-rx",
                rx_gain_db=41,
            )


if __name__ == "__main__":
    unittest.main()
