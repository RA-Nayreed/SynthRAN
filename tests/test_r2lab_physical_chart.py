from __future__ import annotations

from pathlib import Path
import unittest

from synthran.dependencies import load_lock
from synthran.network.r2lab_physical_chart import (
    PINNED_SRSRAN_HELM_COMMIT,
    PhysicalChartBindings,
    R2LabPhysicalChartError,
    build_physical_chart_bundle,
    overlay_pinned_deployment_template,
)
from synthran.network.r2lab_physical_deployment import build_physical_deployment_plan


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class R2LabPhysicalChartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        self.plan = build_physical_deployment_plan(run_id="r2lab-chart")
        self.bindings = PhysicalChartBindings(
            amf_n2_address="198.51.100.200",
            gnb_n2_address="198.51.100.234",
            n300_address="192.0.2.103",
            ru_pod_address="192.0.2.240",
            ru_subnet="192.0.2.0/24",
        )

    def test_bundle_uses_pinned_chart_and_dedicated_physical_image(self) -> None:
        bundle = build_physical_chart_bundle(
            lock=self.lock,
            plan=self.plan,
            bindings=self.bindings,
        ).to_dict()
        values = bundle["values"]
        image = values["image"]

        self.assertEqual(PINNED_SRSRAN_HELM_COMMIT, bundle["chart"]["commit"])
        self.assertEqual("docker.io/r2labuser/srsran-gnb-uhd-csi", image["repository"])
        self.assertEqual("v1.0.0.21", image["tag"])
        self.assertEqual(
            "sha256:7c3bd04fca5e241e9e245c52cc5882bb47c522a55c32b5ed1b9a1ed8fc56a7f2",
            image["digest"],
        )
        self.assertEqual(0, values["replicas"])
        self.assertEqual("Recreate", values["deploymentStrategy"])
        self.assertFalse(values["start"]["logs"])
        self.assertFalse(bundle["execution_enabled"])

    def test_bundle_binds_runtime_network_without_leaking_review_metadata_into_gnb(self) -> None:
        bundle = build_physical_chart_bundle(
            lock=self.lock,
            plan=self.plan,
            bindings=self.bindings,
        ).to_dict()
        values = bundle["values"]
        config = values["gnbConfig"]
        amf = config["cu_cp"]["amf"]

        self.assertEqual(self.bindings.amf_n2_address, amf["addr"])
        self.assertEqual(self.bindings.gnb_n2_address, amf["bind_addr"])
        self.assertEqual(
            f"addr={self.bindings.n300_address},type=n3xx",
            config["ru_sdr"]["device_args"],
        )
        self.assertNotIn("synthran_review", config)
        self.assertTrue(bundle["review"]["reference_aligned"])
        self.assertTrue(bundle["review"]["image_digest_locked"])
        self.assertFalse(bundle["review"]["live_accepted"])

    def test_bundle_preserves_60mhz_2x2_and_removes_srsue_overrides(self) -> None:
        config = build_physical_chart_bundle(
            lock=self.lock,
            plan=self.plan,
            bindings=self.bindings,
        ).to_dict()["values"]["gnbConfig"]
        cell = config["cell_cfg"]

        self.assertEqual(621_984, cell["dl_arfcn"])
        self.assertEqual(60, cell["channel_bandwidth_MHz"])
        self.assertEqual(2, cell["nof_antennas_dl"])
        self.assertEqual(2, cell["nof_antennas_ul"])
        self.assertNotIn("pdcch", cell)
        self.assertNotIn("prach", cell)

    def test_ru_network_is_exact_macvlan_binding(self) -> None:
        values = build_physical_chart_bundle(
            lock=self.lock,
            plan=self.plan,
            bindings=self.bindings,
        ).to_dict()["values"]
        usrp = values["usrp"]

        self.assertEqual("r2lab_usrp", values["ru"])
        self.assertEqual("r2lab_usrp", usrp["master"])
        self.assertEqual("macvlan", usrp["type"])
        self.assertEqual("bridge", usrp["mode"])
        self.assertEqual(9216, usrp["mtu"])
        self.assertEqual("192.0.2.0/24", usrp["ipam"]["subnet"])
        self.assertEqual("sopnode-f3", values["nodeName"])

    def test_invalid_ru_binding_fails_closed(self) -> None:
        with self.assertRaisesRegex(R2LabPhysicalChartError, "reviewed RU subnet"):
            PhysicalChartBindings(
                amf_n2_address="198.51.100.200",
                gnb_n2_address="198.51.100.234",
                n300_address="192.0.2.103",
                ru_pod_address="203.0.113.240",
                ru_subnet="192.0.2.0/24",
            ).validate()

    def test_template_overlay_installs_recreate_zero_replica_and_digest_contract(self) -> None:
        source = """apiVersion: apps/v1
kind: Deployment
spec:
  selector:
    matchLabels:
      app: srsran
  replicas: 1
  template:
    spec:
      containers:
        - name: gnb
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
"""
        overlaid = overlay_pinned_deployment_template(source=source, lock=self.lock)

        self.assertIn("type: {{ .Values.deploymentStrategy }}", overlaid)
        self.assertIn("replicas: {{ .Values.replicas }}", overlaid)
        self.assertIn("@{{ .Values.image.digest }}", overlaid)
        self.assertNotIn("replicas: 1", overlaid)

    def test_template_overlay_rejects_changed_upstream_shape(self) -> None:
        source = """apiVersion: apps/v1
kind: Deployment
spec:
  replicas: 2
"""
        with self.assertRaisesRegex(R2LabPhysicalChartError, "overlay contract"):
            overlay_pinned_deployment_template(source=source, lock=self.lock)


if __name__ == "__main__":
    unittest.main()
