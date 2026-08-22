from __future__ import annotations

from pathlib import Path
import unittest

from synthran.dependencies import load_lock
from synthran.live_preflight import CommandResult
from synthran.r2lab.deployment import (
    PhysicalChartBindings,
    PhysicalChartWorkspace,
    R2LabPhysicalHelmError,
    build_physical_chart_bundle,
    build_physical_deployment_plan,
    render_physical_chart_offline,
    validate_physical_helm_render,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class R2LabPhysicalHelmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        self.bundle = build_physical_chart_bundle(
            lock=self.lock,
            plan=build_physical_deployment_plan(run_id="r2lab-helm"),
            bindings=PhysicalChartBindings(
                amf_n2_address="198.51.100.200",
                gnb_n2_address="198.51.100.234",
                n300_address="192.0.2.103",
                ru_pod_address="192.0.2.240",
                ru_subnet="192.0.2.0/24",
            ),
        )
        image = self.bundle.values["image"]
        self.expected_image = (
            f"{image['repository']}:{image['tag']}@{image['digest']}"
        )

    def valid_render(self) -> str:
        return f"""---
apiVersion: v1
kind: ConfigMap
metadata:
  name: gnb-configmap
data:
  srsran-gnb.yaml: |-
    cu_cp:
      amf:
        addr: 198.51.100.200
        bind_addr: 198.51.100.234
    ru_sdr:
      device_driver: uhd
      device_args: addr=192.0.2.103,type=n3xx
    cell_cfg:
      dl_arfcn: 621984
      band: 78
      channel_bandwidth_MHz: 60
      common_scs: 30
      nof_antennas_dl: 2
      nof_antennas_ul: 2
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: srsran-gnb
spec:
  strategy:
    type: Recreate
  replicas: 0
  template:
    spec:
      containers:
        - name: gnb
          image: {self.expected_image}
"""

    def test_valid_render_is_evidence_but_not_live_acceptance(self) -> None:
        evidence = validate_physical_helm_render(
            text=self.valid_render(), bundle=self.bundle
        )
        payload = evidence.to_dict()
        self.assertEqual(0, payload["replicas"])
        self.assertEqual("Recreate", payload["strategy"])
        self.assertEqual(621_984, payload["carrier_arfcn"])
        self.assertEqual(60, payload["channel_bandwidth_mhz"])
        self.assertEqual(2, payload["antennas_dl"])
        self.assertEqual(2, payload["antennas_ul"])
        self.assertEqual("offline-render-validated", payload["acceptance"])
        self.assertEqual(64, len(payload["sha256"]))

    def test_render_rejects_nonzero_replicas_or_rolling_strategy(self) -> None:
        with self.assertRaisesRegex(R2LabPhysicalHelmError, "remain stopped"):
            validate_physical_helm_render(
                text=self.valid_render().replace("replicas: 0", "replicas: 1"),
                bundle=self.bundle,
            )
        with self.assertRaisesRegex(R2LabPhysicalHelmError, "Recreate"):
            validate_physical_helm_render(
                text=self.valid_render().replace("type: Recreate", "type: RollingUpdate"),
                bundle=self.bundle,
            )

    def test_render_rejects_mutable_image_and_srsue_overrides(self) -> None:
        with self.assertRaisesRegex(R2LabPhysicalHelmError, "digest-locked"):
            validate_physical_helm_render(
                text=self.valid_render().replace(
                    self.expected_image,
                    self.expected_image.split("@", 1)[0],
                ),
                bundle=self.bundle,
            )
        with self.assertRaisesRegex(R2LabPhysicalHelmError, "srsUE-specific"):
            validate_physical_helm_render(
                text=self.valid_render().replace(
                    "      nof_antennas_ul: 2",
                    "      nof_antennas_ul: 2\n      coreset0_index: 12",
                ),
                bundle=self.bundle,
            )

    def test_render_rejects_unpinned_optional_log_sidecar(self) -> None:
        with self.assertRaisesRegex(R2LabPhysicalHelmError, "optional log sidecar"):
            validate_physical_helm_render(
                text=self.valid_render()
                + "      containers:\n        - name: gnb-logs\n          image: busybox\n",
                bundle=self.bundle,
            )

    def test_offline_runner_checks_locked_helm_and_uses_template_only(self) -> None:
        workspace = PhysicalChartWorkspace(
            chart_root=Path("/tmp/chart"),
            deployment_template=Path("/tmp/chart/templates/deployment.yaml"),
            values_file=Path("/tmp/chart/synthran-physical-values.json"),
            source_template_sha256="a" * 64,
            overlaid_template_sha256="b" * 64,
            values_sha256="c" * 64,
        )
        commands: list[tuple[str, ...]] = []

        def runner(command, timeout_seconds: int) -> CommandResult:
            value = tuple(command)
            commands.append(value)
            if value == ("helm", "version", "--short"):
                return CommandResult(0, "v3.18.4+g123\n", "")
            return CommandResult(0, self.valid_render(), "")

        text, evidence = render_physical_chart_offline(
            lock=self.lock,
            bundle=self.bundle,
            workspace=workspace,
            runner=runner,
        )
        self.assertEqual(self.valid_render(), text)
        self.assertEqual(621_984, evidence.carrier_arfcn)
        self.assertEqual(("helm", "version", "--short"), commands[0])
        self.assertEqual("template", commands[1][1])
        self.assertIn("--values", commands[1])
        self.assertNotIn("upgrade", commands[1])
        self.assertNotIn("install", commands[1])

    def test_offline_runner_rejects_unlocked_helm_version(self) -> None:
        workspace = PhysicalChartWorkspace(
            chart_root=Path("/tmp/chart"),
            deployment_template=Path("/tmp/chart/templates/deployment.yaml"),
            values_file=Path("/tmp/chart/synthran-physical-values.json"),
            source_template_sha256="a" * 64,
            overlaid_template_sha256="b" * 64,
            values_sha256="c" * 64,
        )

        def runner(command, timeout_seconds: int) -> CommandResult:
            return CommandResult(0, "v3.19.0\n", "")

        with self.assertRaisesRegex(R2LabPhysicalHelmError, "exactly match"):
            render_physical_chart_offline(
                lock=self.lock,
                bundle=self.bundle,
                workspace=workspace,
                runner=runner,
            )


if __name__ == "__main__":
    unittest.main()
