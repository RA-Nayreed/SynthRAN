"""Pinned Helm/chart adapter for the first physical R2Lab srsRAN gNB.

The accepted virtual adapter remains untouched.  This module maps the reviewed
physical deployment plan into the exact pinned ``srsran-helm`` chart contract
and defines the narrow template overlay required for safe singleton ownership.

The pinned upstream Deployment hard-codes one replica, has no ``Recreate``
strategy, and renders the gNB image by mutable tag only.  The overlay is guarded
by exact anchors and is allowed only for the reviewed chart commit.  If the
upstream shape changes, the adapter fails closed instead of applying a fuzzy
patch.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import ipaddress
import json
import re
from typing import Mapping

from synthran.dependencies import DependencyLock
from synthran.network.r2lab_physical_deployment import R2LabPhysicalDeploymentPlan
from synthran.network.r2lab_physical_render import render_physical_srsran


PINNED_SRSRAN_HELM_COMMIT = "8dfb9890d127734cdcd6eee9df8c5d09b1a8076a"
PHYSICAL_GNB_CONTAINER = "srsran_gnb_physical"
PHYSICAL_CHART_PATH = "charts/srsran-gnb"
PHYSICAL_DEPLOYMENT_TEMPLATE = f"{PHYSICAL_CHART_PATH}/templates/deployment.yaml"
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class R2LabPhysicalChartError(ValueError):
    """Raised when the pinned physical chart contract cannot be proven."""


@dataclass(frozen=True)
class PhysicalChartBindings:
    """Run-time network bindings that remain outside the canonical radio intent."""

    amf_n2_address: str
    gnb_n2_address: str
    n300_address: str
    ru_pod_address: str
    ru_subnet: str
    n3_network_name: str = "n3network"
    ru_master: str = "r2lab_usrp"
    node_name: str = "sopnode-f3"

    def validate(self) -> "PhysicalChartBindings":
        try:
            amf = ipaddress.ip_address(self.amf_n2_address)
            gnb = ipaddress.ip_address(self.gnb_n2_address)
            n300 = ipaddress.ip_address(self.n300_address)
            ru_pod = ipaddress.ip_address(self.ru_pod_address)
            ru_network = ipaddress.ip_network(self.ru_subnet, strict=False)
        except ValueError as exc:
            raise R2LabPhysicalChartError(
                "physical chart bindings must contain valid IP addresses and subnet"
            ) from exc
        if not all(isinstance(value, ipaddress.IPv4Address) for value in (amf, gnb, n300, ru_pod)):
            raise R2LabPhysicalChartError("current physical chart checkpoint is IPv4-only")
        if not isinstance(ru_network, ipaddress.IPv4Network):
            raise R2LabPhysicalChartError("current physical RU subnet must be IPv4")
        if amf == gnb:
            raise R2LabPhysicalChartError("AMF and gNB N2 addresses must differ")
        if n300 not in ru_network or ru_pod not in ru_network:
            raise R2LabPhysicalChartError(
                "N300 and RU pod addresses must belong to the reviewed RU subnet"
            )
        if n300 == ru_pod:
            raise R2LabPhysicalChartError("N300 and RU pod addresses must differ")
        for value, label in (
            (self.n3_network_name, "N3 network name"),
            (self.ru_master, "RU master"),
            (self.node_name, "node name"),
        ):
            if not _SAFE_NAME_RE.fullmatch(value):
                raise R2LabPhysicalChartError(f"{label} contains unsafe characters")
        if self.node_name != "sopnode-f3":
            raise R2LabPhysicalChartError(
                "current physical chart checkpoint requires sopnode-f3"
            )
        if self.ru_master != "r2lab_usrp":
            raise R2LabPhysicalChartError(
                "current physical chart checkpoint requires r2lab_usrp"
            )
        return self


@dataclass(frozen=True)
class PhysicalChartBundle:
    """Offline chart values plus the immutable source contract they depend on."""

    run_id: str
    chart_commit: str
    chart_path: str
    values: Mapping[str, object]
    review: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "synthran/r2lab-physical-chart/v1alpha1",
            "execution_enabled": False,
            "acceptance": "offline-chart-bundle-only",
            "run_id": self.run_id,
            "chart": {
                "commit": self.chart_commit,
                "path": self.chart_path,
            },
            "values": deepcopy(dict(self.values)),
            "review": deepcopy(dict(self.review)),
        }

    def render_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _locked_chart_commit(lock: DependencyLock) -> str:
    git = lock.raw.get("git")
    if not isinstance(git, dict):
        raise R2LabPhysicalChartError("dependency lock Git mapping is unavailable")
    entry = git.get("srsran_helm")
    if not isinstance(entry, dict):
        raise R2LabPhysicalChartError("dependency lock is missing srsran_helm")
    commit = entry.get("commit")
    if commit != PINNED_SRSRAN_HELM_COMMIT:
        raise R2LabPhysicalChartError(
            "physical chart adapter is reviewed only for the pinned srsran_helm commit"
        )
    return commit


def _physical_image(lock: DependencyLock) -> Mapping[str, str]:
    containers = lock.raw.get("containers")
    if not isinstance(containers, dict):
        raise R2LabPhysicalChartError("dependency lock container mapping is unavailable")
    entry = containers.get(PHYSICAL_GNB_CONTAINER)
    if not isinstance(entry, dict):
        raise R2LabPhysicalChartError("physical gNB container lock is missing")
    required = ("image", "tag", "digest", "platform")
    if any(not isinstance(entry.get(key), str) or not entry[key] for key in required):
        raise R2LabPhysicalChartError("physical gNB container lock is incomplete")
    if entry["platform"] != "linux/amd64":
        raise R2LabPhysicalChartError("physical gNB container must be linux/amd64")
    if not entry["digest"].startswith("sha256:"):
        raise R2LabPhysicalChartError("physical gNB container must use a sha256 digest")
    return {key: entry[key] for key in required}


def build_physical_chart_bundle(
    *,
    lock: DependencyLock,
    plan: R2LabPhysicalDeploymentPlan,
    bindings: PhysicalChartBindings,
) -> PhysicalChartBundle:
    """Map the canonical physical plan into pinned chart values without execution."""

    plan.validate()
    bindings.validate()
    chart_commit = _locked_chart_commit(lock)
    image = _physical_image(lock)
    rendered = render_physical_srsran(plan).to_dict()
    gnb_config = deepcopy(rendered["gnb_config"])
    if not isinstance(gnb_config, dict):
        raise R2LabPhysicalChartError("canonical gNB render is malformed")

    review = gnb_config.pop("synthran_review", None)
    if not isinstance(review, dict):
        raise R2LabPhysicalChartError("canonical gNB review metadata is missing")

    cu_cp = gnb_config.get("cu_cp")
    ru_sdr = gnb_config.get("ru_sdr")
    if not isinstance(cu_cp, dict) or not isinstance(cu_cp.get("amf"), dict):
        raise R2LabPhysicalChartError("canonical AMF configuration is malformed")
    if not isinstance(ru_sdr, dict):
        raise R2LabPhysicalChartError("canonical SDR configuration is malformed")
    amf = cu_cp["amf"]
    amf["addr"] = bindings.amf_n2_address
    amf["bind_addr"] = bindings.gnb_n2_address
    ru_sdr["device_args"] = f"addr={bindings.n300_address},type=n3xx"

    values: dict[str, object] = {
        "image": {
            "repository": image["image"],
            "tag": image["tag"],
            "digest": image["digest"],
            "pullPolicy": "IfNotPresent",
        },
        "replicas": 0,
        "deploymentStrategy": "Recreate",
        "resources": {"define": False},
        "start": {
            "gnb": True,
            # The pinned template uses an unpinned busybox when this sidecar is enabled.
            "logs": False,
        },
        "gnbIp": bindings.gnb_n2_address,
        "gnbConfig": gnb_config,
        "n3networkName": bindings.n3_network_name,
        "ru": bindings.ru_master,
        "ruPodIp": bindings.ru_pod_address,
        "usrp": {
            "cniVersion": "0.3.1",
            "type": "macvlan",
            "master": bindings.ru_master,
            "mode": "bridge",
            "mtu": 9216,
            "ipam": {
                "type": "host-local",
                "subnet": bindings.ru_subnet,
            },
        },
        "nodeName": bindings.node_name,
        "sriov": {"enabled": False},
    }

    serialized = json.dumps(values, sort_keys=True).lower()
    if "rfsim" in serialized or "all-off" in serialized:
        raise R2LabPhysicalChartError("physical chart bundle contains forbidden backend behavior")
    cell_cfg = gnb_config.get("cell_cfg")
    if not isinstance(cell_cfg, dict):
        raise R2LabPhysicalChartError("canonical cell configuration is malformed")
    if "pdcch" in cell_cfg or "prach" in cell_cfg:
        raise R2LabPhysicalChartError(
            "physical chart bundle inherited srsUE-specific radio overrides"
        )

    return PhysicalChartBundle(
        run_id=plan.run_id,
        chart_commit=chart_commit,
        chart_path=PHYSICAL_CHART_PATH,
        values=values,
        review={
            **review,
            "image_digest_locked": True,
            "singleton_deployment": True,
            "logs_sidecar_disabled": True,
            "live_accepted": False,
        },
    )


def overlay_pinned_deployment_template(
    *, source: str, lock: DependencyLock
) -> str:
    """Apply the exact singleton/digest overlay to the reviewed chart template."""

    _locked_chart_commit(lock)
    anchors = {
        "spec:\n  selector:\n": (
            "spec:\n"
            "  strategy:\n"
            "    type: {{ .Values.deploymentStrategy }}\n"
            "  selector:\n"
        ),
        "  replicas: 1\n": "  replicas: {{ .Values.replicas }}\n",
        '          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"\n': (
            '          image: "{{ .Values.image.repository }}:'
            '{{ .Values.image.tag }}@{{ .Values.image.digest }}"\n'
        ),
    }
    result = source
    for anchor, replacement in anchors.items():
        count = result.count(anchor)
        if count != 1:
            raise R2LabPhysicalChartError(
                "pinned srsRAN Deployment template no longer matches the reviewed overlay contract"
            )
        result = result.replace(anchor, replacement, 1)

    if "  replicas: 1\n" in result:
        raise R2LabPhysicalChartError("hard-coded gNB replica count survived the overlay")
    if "@{{ .Values.image.digest }}" not in result:
        raise R2LabPhysicalChartError("digest-locked image rendering was not installed")
    if "type: {{ .Values.deploymentStrategy }}" not in result:
        raise R2LabPhysicalChartError("singleton Deployment strategy was not installed")
    return result
