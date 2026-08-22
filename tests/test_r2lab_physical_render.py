from __future__ import annotations

import unittest

from synthran.r2lab.deployment import (
    AMF_ADDRESS_PLACEHOLDER,
    GNB_BIND_ADDRESS_PLACEHOLDER,
    N300_DEVICE_ARGS_PLACEHOLDER,
    build_physical_deployment_plan,
    render_physical_srsran,
)


class R2LabPhysicalRenderTests(unittest.TestCase):
    def test_render_preserves_reference_aligned_radio_semantics(self) -> None:
        rendered = render_physical_srsran(
            build_physical_deployment_plan(run_id="r2lab-render")
        )
        payload = rendered.to_dict()
        config = payload["gnb_config"]
        cell = config["cell_cfg"]

        self.assertEqual(621_984, cell["dl_arfcn"])
        self.assertEqual(78, cell["band"])
        self.assertEqual(60, cell["channel_bandwidth_MHz"])
        self.assertEqual(30, cell["common_scs"])
        self.assertEqual(2, cell["nof_antennas_dl"])
        self.assertEqual(2, cell["nof_antennas_ul"])
        self.assertEqual([{"sst": 1}], cell["slicing"])
        self.assertEqual(621_312, config["synthran_review"]["expected_ssb_arfcn"])
        self.assertEqual(620_040, config["synthran_review"]["reference_point_a_arfcn"])
        self.assertFalse(config["synthran_review"]["live_accepted"])

    def test_render_matches_pinned_cu_cp_and_remote_control_shape(self) -> None:
        config = render_physical_srsran(
            build_physical_deployment_plan(run_id="r2lab-chart-shape")
        ).to_dict()["gnb_config"]
        amf = config["cu_cp"]["amf"]

        self.assertEqual(AMF_ADDRESS_PLACEHOLDER, amf["addr"])
        self.assertEqual(GNB_BIND_ADDRESS_PLACEHOLDER, amf["bind_addr"])
        self.assertEqual(38412, amf["port"])
        self.assertEqual(8001, config["remote_control"]["port"])
        self.assertTrue(config["remote_control"]["enabled"])
        self.assertEqual(
            [{"sst": 1}],
            amf["supported_tracking_areas"][0]["plmn_list"][0][
                "tai_slice_support_list"
            ],
        )

    def test_render_keeps_runtime_network_values_as_placeholders(self) -> None:
        config = render_physical_srsran(
            build_physical_deployment_plan(run_id="r2lab-placeholders")
        ).to_dict()["gnb_config"]
        amf = config["cu_cp"]["amf"]

        self.assertEqual(AMF_ADDRESS_PLACEHOLDER, amf["addr"])
        self.assertEqual(GNB_BIND_ADDRESS_PLACEHOLDER, amf["bind_addr"])
        self.assertEqual(N300_DEVICE_ARGS_PLACEHOLDER, config["ru_sdr"]["device_args"])

    def test_render_is_uhd_recreate_and_stopped_before_lifecycle_start(self) -> None:
        payload = render_physical_srsran(
            build_physical_deployment_plan(run_id="r2lab-recreate")
        ).to_dict()

        self.assertEqual("uhd", payload["gnb_config"]["ru_sdr"]["device_driver"])
        self.assertEqual(0, payload["deployment"]["replicas"])
        self.assertEqual("Recreate", payload["deployment"]["strategy"]["type"])
        self.assertEqual(1, payload["deployment"]["desired_replicas_after_lifecycle_start"])
        self.assertFalse(payload["execution_ready"])
        self.assertEqual("offline-render-only", payload["acceptance"])

    def test_render_does_not_inherit_srsue_specific_overrides(self) -> None:
        cell = render_physical_srsran(
            build_physical_deployment_plan(run_id="r2lab-cots")
        ).to_dict()["gnb_config"]["cell_cfg"]

        self.assertNotIn("pdcch", cell)
        self.assertNotIn("prach", cell)
        self.assertNotIn("coreset0_index", str(cell))
        self.assertNotIn("prach_config_index", str(cell))

    def test_render_contains_no_rfsim_settings(self) -> None:
        text = render_physical_srsran(
            build_physical_deployment_plan(run_id="r2lab-physical-clean-render")
        ).render_json()
        self.assertNotIn("rfsim", text.lower())


if __name__ == "__main__":
    unittest.main()
