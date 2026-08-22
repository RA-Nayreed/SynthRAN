"""Materialize the reviewed physical chart overlay in an isolated worktree.

This module performs filesystem-only preparation.  It never contacts Kubernetes,
R2Lab, or SLICES.  The caller is responsible for creating an isolated checkout
of the locked ``srsran-helm`` commit; this code then applies the exact guarded
Deployment overlay and writes the generated values as JSON, which Helm accepts
as a values document.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from synthran.dependencies import DependencyLock
from synthran.network.r2lab_physical_chart import (
    PHYSICAL_CHART_PATH,
    PHYSICAL_DEPLOYMENT_TEMPLATE,
    PhysicalChartBundle,
    R2LabPhysicalChartError,
    overlay_pinned_deployment_template,
)


VALUES_FILE_NAME = "synthran-physical-values.json"


@dataclass(frozen=True)
class PhysicalChartWorkspace:
    chart_root: Path
    deployment_template: Path
    values_file: Path
    source_template_sha256: str
    overlaid_template_sha256: str
    values_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "chart_root": PHYSICAL_CHART_PATH,
            "deployment_template": "templates/deployment.yaml",
            "values_file": VALUES_FILE_NAME,
            "source_template_sha256": self.source_template_sha256,
            "overlaid_template_sha256": self.overlaid_template_sha256,
            "values_sha256": self.values_sha256,
        }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def materialize_physical_chart_workspace(
    *,
    checkout_root: Path,
    lock: DependencyLock,
    bundle: PhysicalChartBundle,
) -> PhysicalChartWorkspace:
    """Apply the guarded overlay and write one immutable generated values file."""

    chart_root = checkout_root / PHYSICAL_CHART_PATH
    template_path = checkout_root / PHYSICAL_DEPLOYMENT_TEMPLATE
    chart_metadata = chart_root / "Chart.yaml"
    values_path = chart_root / VALUES_FILE_NAME

    if not chart_root.is_dir() or not chart_metadata.is_file() or not template_path.is_file():
        raise R2LabPhysicalChartError(
            "isolated srsran_helm checkout is missing the reviewed chart structure"
        )
    if values_path.exists():
        raise R2LabPhysicalChartError(
            "physical chart workspace already contains generated SynthRAN values"
        )

    try:
        source = template_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise R2LabPhysicalChartError(
            "unable to read the pinned physical Deployment template"
        ) from exc

    overlaid = overlay_pinned_deployment_template(source=source, lock=lock)
    values_text = json.dumps(bundle.values, indent=2, sort_keys=True) + "\n"

    try:
        template_path.write_text(overlaid, encoding="utf-8", newline="\n")
        values_path.write_text(values_text, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise R2LabPhysicalChartError(
            "unable to materialize the physical chart workspace"
        ) from exc

    return PhysicalChartWorkspace(
        chart_root=chart_root,
        deployment_template=template_path,
        values_file=values_path,
        source_template_sha256=_sha256_text(source),
        overlaid_template_sha256=_sha256_text(overlaid),
        values_sha256=_sha256_text(values_text),
    )
