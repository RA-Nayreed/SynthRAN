from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from synthran.network.r2lab_physical_artifact import (
    R2LabPhysicalArtifactError,
    package_physical_chart,
)
from synthran.network.r2lab_physical_chart_workspace import PhysicalChartWorkspace


class R2LabPhysicalArtifactTests(unittest.TestCase):
    def make_workspace(self, root: Path) -> PhysicalChartWorkspace:
        chart = root / "charts" / "srsran-gnb"
        templates = chart / "templates"
        templates.mkdir(parents=True)
        (chart / "Chart.yaml").write_text("apiVersion: v2\nname: srsran-gnb\nversion: 0.1.0\n")
        deployment = templates / "deployment.yaml"
        deployment.write_text("kind: Deployment\n")
        values = chart / "synthran-physical-values.json"
        values.write_text('{"replicas": 0}\n')
        return PhysicalChartWorkspace(
            chart_root=chart,
            deployment_template=deployment,
            values_file=values,
            source_template_sha256="a" * 64,
            overlaid_template_sha256="b" * 64,
            values_sha256="c" * 64,
        )

    def test_same_workspace_packages_to_same_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self.make_workspace(root / "source")
            first = package_physical_chart(
                workspace=workspace,
                run_id="r2lab-artifact",
                destination=root / "out-a",
            )
            second = package_physical_chart(
                workspace=workspace,
                run_id="r2lab-artifact",
                destination=root / "out-b",
            )

            self.assertEqual(first.package_sha256, second.package_sha256)
            self.assertEqual("c" * 64, first.values_sha256)
            self.assertEqual("offline-packaged-only", first.to_dict()["acceptance"])
            self.assertTrue(first.package_path.is_file())

    def test_package_changes_when_chart_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self.make_workspace(root / "source")
            first = package_physical_chart(
                workspace=workspace,
                run_id="r2lab-artifact-a",
                destination=root / "out-a",
            )
            workspace.deployment_template.write_text("kind: Deployment\nmetadata:\n  name: changed\n")
            second = package_physical_chart(
                workspace=workspace,
                run_id="r2lab-artifact-b",
                destination=root / "out-b",
            )
            self.assertNotEqual(first.package_sha256, second.package_sha256)

    def test_existing_package_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self.make_workspace(root / "source")
            destination = root / "out"
            package_physical_chart(
                workspace=workspace,
                run_id="r2lab-artifact",
                destination=destination,
            )
            with self.assertRaisesRegex(R2LabPhysicalArtifactError, "already exists"):
                package_physical_chart(
                    workspace=workspace,
                    run_id="r2lab-artifact",
                    destination=destination,
                )

    def test_symbolic_links_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = self.make_workspace(root / "source")
            target = workspace.chart_root / "Chart.yaml"
            link = workspace.chart_root / "templates" / "linked.yaml"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symbolic links are unavailable on this platform")
            with self.assertRaisesRegex(R2LabPhysicalArtifactError, "symbolic links"):
                package_physical_chart(
                    workspace=workspace,
                    run_id="r2lab-artifact",
                    destination=root / "out",
                )


if __name__ == "__main__":
    unittest.main()
