from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from synthran.dependencies import load_lock
from synthran.network.r2lab_physical_chart import (
    PhysicalChartBindings,
    R2LabPhysicalChartError,
    build_physical_chart_bundle,
)
from synthran.network.r2lab_physical_chart_workspace import (
    VALUES_FILE_NAME,
    materialize_physical_chart_workspace,
)
from synthran.network.r2lab_physical_deployment import build_physical_deployment_plan


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


DEPLOYMENT_FIXTURE = """apiVersion: apps/v1
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


class R2LabPhysicalChartWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        self.bundle = build_physical_chart_bundle(
            lock=self.lock,
            plan=build_physical_deployment_plan(run_id="r2lab-workspace"),
            bindings=PhysicalChartBindings(
                amf_n2_address="198.51.100.200",
                gnb_n2_address="198.51.100.234",
                n300_address="192.0.2.103",
                ru_pod_address="192.0.2.240",
                ru_subnet="192.0.2.0/24",
            ),
        )

    def test_workspace_applies_overlay_and_writes_json_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chart = root / "charts" / "srsran-gnb"
            templates = chart / "templates"
            templates.mkdir(parents=True)
            (chart / "Chart.yaml").write_text("apiVersion: v2\nname: srsran-gnb\n")
            deployment = templates / "deployment.yaml"
            deployment.write_text(DEPLOYMENT_FIXTURE)

            result = materialize_physical_chart_workspace(
                checkout_root=root,
                lock=self.lock,
                bundle=self.bundle,
            )

            overlaid = deployment.read_text()
            self.assertIn("type: {{ .Values.deploymentStrategy }}", overlaid)
            self.assertIn("replicas: {{ .Values.replicas }}", overlaid)
            self.assertIn("@{{ .Values.image.digest }}", overlaid)
            self.assertNotEqual(
                result.source_template_sha256,
                result.overlaid_template_sha256,
            )

            values_path = chart / VALUES_FILE_NAME
            values = json.loads(values_path.read_text())
            self.assertEqual(0, values["replicas"])
            self.assertEqual("Recreate", values["deploymentStrategy"])
            self.assertEqual(
                self.bundle.values["image"]["digest"],
                values["image"]["digest"],
            )
            self.assertEqual(64, len(result.values_sha256))

    def test_workspace_refuses_overwrite_of_generated_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chart = root / "charts" / "srsran-gnb"
            templates = chart / "templates"
            templates.mkdir(parents=True)
            (chart / "Chart.yaml").write_text("apiVersion: v2\nname: srsran-gnb\n")
            (templates / "deployment.yaml").write_text(DEPLOYMENT_FIXTURE)
            (chart / VALUES_FILE_NAME).write_text("{}\n")

            with self.assertRaisesRegex(R2LabPhysicalChartError, "already contains"):
                materialize_physical_chart_workspace(
                    checkout_root=root,
                    lock=self.lock,
                    bundle=self.bundle,
                )

    def test_workspace_requires_reviewed_chart_structure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(R2LabPhysicalChartError, "chart structure"):
                materialize_physical_chart_workspace(
                    checkout_root=Path(directory),
                    lock=self.lock,
                    bundle=self.bundle,
                )


if __name__ == "__main__":
    unittest.main()
