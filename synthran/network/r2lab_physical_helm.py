"""Offline Helm rendering and validation for the physical R2Lab gNB chart.

The physical chart must be fully rendered before any Kubernetes mutation.  This
module executes only local Helm commands against an already-materialized isolated
chart workspace, then validates the rendered text against the canonical bundle.
It does not contact a cluster.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Callable, Sequence

from synthran.dependencies import DependencyLock
from synthran.live_preflight import CommandResult
from synthran.network.r2lab_physical_chart import PhysicalChartBundle
from synthran.network.r2lab_physical_chart_workspace import PhysicalChartWorkspace


class R2LabPhysicalHelmError(RuntimeError):
    """Raised when local physical Helm rendering cannot be proven safe."""


Runner = Callable[[Sequence[str], int], CommandResult]


@dataclass(frozen=True)
class PhysicalHelmRenderEvidence:
    sha256: str
    replicas: int
    strategy: str
    image_reference: str
    carrier_arfcn: int
    channel_bandwidth_mhz: int
    antennas_dl: int
    antennas_ul: int

    def to_dict(self) -> dict[str, object]:
        return {
            "sha256": self.sha256,
            "replicas": self.replicas,
            "strategy": self.strategy,
            "image_reference": self.image_reference,
            "carrier_arfcn": self.carrier_arfcn,
            "channel_bandwidth_mhz": self.channel_bandwidth_mhz,
            "antennas_dl": self.antennas_dl,
            "antennas_ul": self.antennas_ul,
            "acceptance": "offline-render-validated",
        }


def _locked_helm_version(lock: DependencyLock) -> str:
    tools = lock.raw.get("tools")
    entry = tools.get("helm_linux_amd64") if isinstance(tools, dict) else None
    version = entry.get("version") if isinstance(entry, dict) else None
    if not isinstance(version, str) or not version:
        raise R2LabPhysicalHelmError("dependency lock does not define the Helm version")
    return version


def _expected_image(bundle: PhysicalChartBundle) -> str:
    image = bundle.values.get("image")
    if not isinstance(image, dict):
        raise R2LabPhysicalHelmError("physical chart bundle image metadata is missing")
    repository = image.get("repository")
    tag = image.get("tag")
    digest = image.get("digest")
    if not all(isinstance(value, str) and value for value in (repository, tag, digest)):
        raise R2LabPhysicalHelmError("physical chart bundle image metadata is incomplete")
    return f"{repository}:{tag}@{digest}"


def _integer_after(text: str, key: str) -> int:
    matches = re.findall(rf"(?m)^\s*{re.escape(key)}:\s*([0-9]+)\s*$", text)
    if len(matches) != 1:
        raise R2LabPhysicalHelmError(
            f"rendered physical chart must contain exactly one {key} value"
        )
    return int(matches[0])


def validate_physical_helm_render(
    *, text: str, bundle: PhysicalChartBundle
) -> PhysicalHelmRenderEvidence:
    """Validate the fully rendered chart text before it may reach a cluster."""

    if not text.strip():
        raise R2LabPhysicalHelmError("Helm rendered no physical chart output")
    expected_image = _expected_image(bundle)
    if text.count(expected_image) != 1:
        raise R2LabPhysicalHelmError(
            "rendered physical chart must contain exactly one digest-locked gNB image"
        )
    if not re.search(r"(?m)^kind:\s*Deployment\s*$", text):
        raise R2LabPhysicalHelmError("rendered physical chart is missing the gNB Deployment")
    replicas = _integer_after(text, "replicas")
    if replicas != 0:
        raise R2LabPhysicalHelmError("rendered physical gNB must remain stopped")
    strategy_matches = re.findall(
        r"(?ms)^\s*strategy:\s*\n\s*type:\s*([A-Za-z]+)\s*$",
        text,
    )
    if strategy_matches != ["Recreate"]:
        raise R2LabPhysicalHelmError(
            "rendered physical gNB must use exactly one Recreate strategy"
        )

    carrier = _integer_after(text, "dl_arfcn")
    bandwidth = _integer_after(text, "channel_bandwidth_MHz")
    antennas_dl = _integer_after(text, "nof_antennas_dl")
    antennas_ul = _integer_after(text, "nof_antennas_ul")
    if carrier != 621_984 or bandwidth != 60 or antennas_dl != 2 or antennas_ul != 2:
        raise R2LabPhysicalHelmError(
            "rendered physical radio values do not match the reviewed offline intent"
        )
    lowered = text.lower()
    if "coreset0_index" in lowered or "prach_config_index" in lowered:
        raise R2LabPhysicalHelmError(
            "rendered physical chart inherited srsUE-specific radio overrides"
        )
    if re.search(r"(?m)^\s*image:\s*busybox(?::|\s|$)", text):
        raise R2LabPhysicalHelmError(
            "rendered physical chart contains the unpinned optional log sidecar"
        )
    if "rfsim" in lowered or "all-off" in lowered:
        raise R2LabPhysicalHelmError("rendered physical chart contains forbidden backend behavior")

    return PhysicalHelmRenderEvidence(
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        replicas=replicas,
        strategy="Recreate",
        image_reference=expected_image,
        carrier_arfcn=carrier,
        channel_bandwidth_mhz=bandwidth,
        antennas_dl=antennas_dl,
        antennas_ul=antennas_ul,
    )


def render_physical_chart_offline(
    *,
    lock: DependencyLock,
    bundle: PhysicalChartBundle,
    workspace: PhysicalChartWorkspace,
    runner: Runner,
    timeout_seconds: int = 60,
) -> tuple[str, PhysicalHelmRenderEvidence]:
    """Run locked local Helm template and validate its output; never contact Kubernetes."""

    if timeout_seconds < 1 or timeout_seconds > 300:
        raise R2LabPhysicalHelmError("offline Helm timeout must be between 1 and 300 seconds")
    expected_version = _locked_helm_version(lock)
    try:
        version_result = runner(("helm", "version", "--short"), timeout_seconds)
    except Exception as exc:
        raise R2LabPhysicalHelmError("locked Helm executable could not be inspected") from exc
    if version_result.returncode != 0:
        raise R2LabPhysicalHelmError("Helm version probe returned nonzero")
    match = re.search(r"v?([0-9]+\.[0-9]+\.[0-9]+)", version_result.stdout)
    if match is None or match.group(1) != expected_version:
        raise R2LabPhysicalHelmError(
            f"Helm must exactly match locked version {expected_version}"
        )

    command = (
        "helm",
        "template",
        "srsran-gnb",
        str(workspace.chart_root),
        "--namespace",
        "open5gs",
        "--values",
        str(workspace.values_file),
    )
    try:
        result = runner(command, timeout_seconds)
    except Exception as exc:
        raise R2LabPhysicalHelmError("offline Helm template command failed") from exc
    if result.returncode != 0:
        raise R2LabPhysicalHelmError("offline Helm template command returned nonzero")
    evidence = validate_physical_helm_render(text=result.stdout, bundle=bundle)
    return result.stdout, evidence
