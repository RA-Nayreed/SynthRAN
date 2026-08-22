"""Canonical offline render for the first physical R2Lab srsRAN profile.

This renderer sits between the reviewed physical deployment plan and the pinned
Helm/chart adapter. It produces the semantic gNB configuration we intend to hand
to srsRAN while keeping live network bindings as explicit placeholders.

The pinned chart stores AMF settings below ``cu_cp.amf`` and reads the remote
control port from ``gnbConfig.remote_control``. The canonical render mirrors that
shape instead of inventing a parallel schema. The Deployment is rendered stopped
with ``Recreate``; the singleton lifecycle controller may start one pod only
after the stopped configuration is applied and reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

from synthran.network.r2lab_physical_deployment import R2LabPhysicalDeploymentPlan


AMF_ADDRESS_PLACEHOLDER = "<AMF_N2_ADDRESS>"
GNB_BIND_ADDRESS_PLACEHOLDER = "<GNB_N2_ADDRESS>"
N300_DEVICE_ARGS_PLACEHOLDER = "<N300_UHD_DEVICE_ARGS>"


class R2LabPhysicalRenderError(ValueError):
    """Raised when the canonical physical render violates reviewed semantics."""


@dataclass(frozen=True)
class PhysicalSrsranRender:
    run_id: str
    gnb_config: Mapping[str, object]
    deployment: Mapping[str, object]

    def validate(self) -> "PhysicalSrsranRender":
        ru_sdr = self.gnb_config.get("ru_sdr")
        cell_cfg = self.gnb_config.get("cell_cfg")
        cu_cp = self.gnb_config.get("cu_cp")
        remote_control = self.gnb_config.get("remote_control")
        if not isinstance(ru_sdr, dict) or not isinstance(cell_cfg, dict):
            raise R2LabPhysicalRenderError(
                "physical render is missing SDR or cell configuration"
            )
        if not isinstance(cu_cp, dict) or not isinstance(cu_cp.get("amf"), dict):
            raise R2LabPhysicalRenderError(
                "physical render is missing the pinned cu_cp AMF configuration"
            )
        if not isinstance(remote_control, dict) or remote_control.get("port") != 8001:
            raise R2LabPhysicalRenderError(
                "physical render must expose the pinned-chart remote control port"
            )
        amf = cu_cp["amf"]
        if ru_sdr.get("device_driver") != "uhd":
            raise R2LabPhysicalRenderError("physical render must use the UHD radio driver")
        if "rfsim" in json.dumps(self.gnb_config).lower():
            raise R2LabPhysicalRenderError("physical render must not contain RFSIM settings")
        if cell_cfg.get("band") != 78:
            raise R2LabPhysicalRenderError(
                "physical render must stay in the reviewed band 78 checkpoint"
            )
        if cell_cfg.get("channel_bandwidth_MHz") != 60:
            raise R2LabPhysicalRenderError(
                "physical render must preserve the reviewed 60 MHz intent"
            )
        if cell_cfg.get("common_scs") != 30:
            raise R2LabPhysicalRenderError(
                "physical render must preserve the reviewed 30 kHz SCS"
            )
        if cell_cfg.get("nof_antennas_dl") != 2 or cell_cfg.get("nof_antennas_ul") != 2:
            raise R2LabPhysicalRenderError(
                "physical render must preserve the reviewed 2x2 intent"
            )
        if "pdcch" in cell_cfg or "prach" in cell_cfg:
            raise R2LabPhysicalRenderError(
                "physical render must not inherit srsUE-specific PDCCH/PRACH overrides"
            )
        if amf.get("addr") != AMF_ADDRESS_PLACEHOLDER:
            raise R2LabPhysicalRenderError(
                "AMF address must remain an explicit runtime placeholder"
            )
        if amf.get("bind_addr") != GNB_BIND_ADDRESS_PLACEHOLDER:
            raise R2LabPhysicalRenderError(
                "gNB N2 bind address must remain an explicit runtime placeholder"
            )
        if ru_sdr.get("device_args") != N300_DEVICE_ARGS_PLACEHOLDER:
            raise R2LabPhysicalRenderError(
                "N300 device arguments must remain an explicit runtime placeholder"
            )
        if self.deployment.get("replicas") != 0:
            raise R2LabPhysicalRenderError(
                "configuration render must keep the physical gNB stopped"
            )
        strategy = self.deployment.get("strategy")
        if not isinstance(strategy, dict) or strategy.get("type") != "Recreate":
            raise R2LabPhysicalRenderError("physical Deployment strategy must be Recreate")
        return self

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": "synthran/r2lab-physical-render/v1alpha1",
            "run_id": self.run_id,
            "execution_ready": False,
            "acceptance": "offline-render-only",
            "gnb_config": dict(self.gnb_config),
            "deployment": dict(self.deployment),
            "runtime_placeholders": [
                AMF_ADDRESS_PLACEHOLDER,
                GNB_BIND_ADDRESS_PLACEHOLDER,
                N300_DEVICE_ARGS_PLACEHOLDER,
            ],
        }

    def render_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def render_physical_srsran(plan: R2LabPhysicalDeploymentPlan) -> PhysicalSrsranRender:
    """Render the reviewed plan into pinned-chart srsRAN semantics offline."""

    plan.validate()
    intent = plan.radio_intent.validate()
    profile = intent.profile

    gnb_config: dict[str, object] = {
        "cu_cp": {
            "inactivity_timer": 7200,
            "request_pdu_session_timeout": 30,
            "amf": {
                "sctp_rto_initial": 200,
                "sctp_rto_min": 200,
                "sctp_rto_max": 2000,
                "sctp_init_max_attempts": 5,
                "sctp_hb_interval": 1000,
                "sctp_assoc_max_retx": 5,
                "sctp_nodelay": True,
                "addr": AMF_ADDRESS_PLACEHOLDER,
                "port": 38412,
                "bind_addr": GNB_BIND_ADDRESS_PLACEHOLDER,
                "supported_tracking_areas": [
                    {
                        "tac": 1,
                        "plmn_list": [
                            {
                                "plmn": "00101",
                                "tai_slice_support_list": [{"sst": 1}],
                            }
                        ],
                    }
                ],
            },
        },
        "ru_sdr": {
            "device_driver": "uhd",
            "device_args": N300_DEVICE_ARGS_PLACEHOLDER,
            "srate": 61.44,
            "tx_gain": plan.tx_gain_db,
            "rx_gain": plan.rx_gain_db,
            "clock": "internal",
            "sync": "internal",
        },
        "cell_cfg": {
            "dl_arfcn": profile.carrier.value,
            "band": profile.band,
            "channel_bandwidth_MHz": profile.channel_bandwidth_mhz,
            "common_scs": profile.common_scs_khz,
            "plmn": "00101",
            "tac": 1,
            "nof_antennas_dl": profile.nof_antennas_dl,
            "nof_antennas_ul": profile.nof_antennas_ul,
            "slicing": [{"sst": 1}],
        },
        "log": {
            "filename": "/tmp/gnb.log",
            "all_level": "warning",
            "config_level": "debug",
        },
        "pcap": {
            "mac_enable": False,
            "mac_filename": "/tmp/gnb_mac.pcap",
            "ngap_enable": False,
            "ngap_filename": "/tmp/gnb_ngap.pcap",
        },
        "remote_control": {
            "bind_addr": "0.0.0.0",
            "enabled": True,
            "port": 8001,
        },
        "synthran_review": {
            "carrier_semantic": profile.carrier.semantic.value,
            "expected_ssb_arfcn": intent.expected_ssb.value,
            "reference_point_a_arfcn": intent.reference.point_a.value,
            "reference_aligned": True,
            "live_accepted": False,
        },
    }

    deployment = {
        "replicas": 0,
        "strategy": {"type": "Recreate"},
        "selector": "app=srsran,component=gnb",
        "desired_replicas_after_lifecycle_start": 1,
    }

    return PhysicalSrsranRender(
        run_id=plan.run_id,
        gnb_config=gnb_config,
        deployment=deployment,
    ).validate()
