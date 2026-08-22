"""Separate offline deployment boundary for the physical R2Lab backend.

The accepted virtual adapter in :mod:`synthran.fiveg_ansible` deliberately
supports only ``rfsim``.  Physical work must not weaken that invariant.  This
module defines a distinct, non-executing R2Lab deployment plan around the
reviewed first physical topology and the reference-aligned radio intent.

The plan is intentionally conservative: the current checkpoint accepts only the
known two-node core/RAN split and N300 radio, records the required singleton gNB
lifecycle, and refuses srsUE-specific radio overrides.  A later live adapter can
consume this plan once its rendered Helm values are reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass
import json

from synthran.network.r2lab_radio_profile import (
    ReferenceAlignedPhysicalIntent,
    R2LabRadioProfileError,
    r2lab_oai_aligned_candidate,
)
from synthran.network.runtime import validate_run_id


PHYSICAL_DEPLOYMENT_SCHEMA = "synthran/r2lab-physical-deployment/v1alpha1"
CURRENT_CORE_NODE = "sopnode-f2"
CURRENT_RAN_NODE = "sopnode-f3"
CURRENT_RADIO = "n300"


class R2LabPhysicalDeploymentError(ValueError):
    """Raised when a physical deployment plan crosses the reviewed boundary."""


@dataclass(frozen=True)
class R2LabPhysicalDeploymentPlan:
    """Non-executing physical deployment plan for one reviewed R2Lab topology."""

    run_id: str
    core_node: str
    ran_node: str
    radio: str
    radio_intent: ReferenceAlignedPhysicalIntent
    tx_gain_db: int = 25
    rx_gain_db: int = 35

    def validate(self) -> "R2LabPhysicalDeploymentPlan":
        try:
            validate_run_id(self.run_id)
        except Exception as exc:
            raise R2LabPhysicalDeploymentError(str(exc)) from exc
        if self.core_node != CURRENT_CORE_NODE:
            raise R2LabPhysicalDeploymentError(
                f"current physical checkpoint requires core node {CURRENT_CORE_NODE}"
            )
        if self.ran_node != CURRENT_RAN_NODE:
            raise R2LabPhysicalDeploymentError(
                f"current physical checkpoint requires RAN node {CURRENT_RAN_NODE}"
            )
        if self.core_node == self.ran_node:
            raise R2LabPhysicalDeploymentError("physical core and RAN nodes must differ")
        if self.radio != CURRENT_RADIO:
            raise R2LabPhysicalDeploymentError(
                f"current physical checkpoint requires radio {CURRENT_RADIO}"
            )
        if self.tx_gain_db < 0 or self.tx_gain_db > 30:
            raise R2LabPhysicalDeploymentError(
                "physical N300 TX gain must stay within the reviewed 0-30 dB checkpoint range"
            )
        if self.rx_gain_db < 0 or self.rx_gain_db > 40:
            raise R2LabPhysicalDeploymentError(
                "physical N300 RX gain must stay within the reviewed 0-40 dB checkpoint range"
            )
        try:
            self.radio_intent.validate()
        except R2LabRadioProfileError as exc:
            raise R2LabPhysicalDeploymentError(
                "physical radio intent is not reference aligned"
            ) from exc
        return self

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": PHYSICAL_DEPLOYMENT_SCHEMA,
            "execution_enabled": False,
            "acceptance": "offline-plan-only",
            "run_id": self.run_id,
            "backend": "r2lab",
            "core": "open5gs",
            "ran": "srsran",
            "radio": self.radio,
            "nodes": {
                "core": self.core_node,
                "ran": self.ran_node,
            },
            "radio_intent": self.radio_intent.to_dict(),
            "gains_db": {
                "tx": self.tx_gain_db,
                "rx": self.rx_gain_db,
            },
            "deployment": {
                "strategy": "Recreate",
                "desired_replicas": 1,
                "max_concurrent_gnb_pods": 1,
                "srsue_specific_overrides": False,
                "coreset0_index_override": None,
                "prach_config_index_override": None,
            },
            "required_lifecycle": [
                "scale exact srsran-gnb deployment to zero",
                "prove matching gNB pod count is zero",
                "allow UHD claim release",
                "apply reviewed physical configuration",
                "scale exact srsran-gnb deployment to one",
                "prove exactly one matching pod is Running and ready",
            ],
            "safety": {
                "automatic_r2lab_booking": False,
                "global_power_off": False,
                "rolling_overlap_allowed": False,
                "virtual_adapter_modified": False,
                "live_acceptance_claimed": False,
            },
        }

    def render(self, *, as_json: bool = False) -> str:
        payload = self.to_dict()
        if as_json:
            return json.dumps(payload, indent=2, sort_keys=True)
        carrier = payload["radio_intent"]["profile"]["carrier"]
        expected_ssb = payload["radio_intent"]["expected_ssb"]
        return "\n".join(
            (
                "SynthRAN physical R2Lab deployment plan (NON-EXECUTING)",
                f"Run ID: {self.run_id}",
                f"Path: Open5GS@{self.core_node} + srsRAN@{self.ran_node} + {self.radio}",
                (
                    "Carrier: "
                    f"ARFCN {carrier['arfcn']} ({carrier['frequency_mhz']:.2f} MHz, carrier-center)"
                ),
                (
                    "Expected SSB reference: "
                    f"ARFCN {expected_ssb['arfcn']} ({expected_ssb['frequency_mhz']:.2f} MHz)"
                ),
                "Radio intent: reference-aligned offline candidate; not live accepted",
                "Deployment strategy: Recreate / maximum one matching gNB pod",
                "srsUE-specific CORESET/PRACH overrides: disabled",
                "Execution: disabled until rendered physical values are reviewed",
            )
        )


def build_physical_deployment_plan(
    *,
    run_id: str,
    core_node: str = CURRENT_CORE_NODE,
    ran_node: str = CURRENT_RAN_NODE,
    radio: str = CURRENT_RADIO,
    radio_intent: ReferenceAlignedPhysicalIntent | None = None,
    tx_gain_db: int = 25,
    rx_gain_db: int = 35,
) -> R2LabPhysicalDeploymentPlan:
    """Build the current conservative physical plan without contacting providers."""

    return R2LabPhysicalDeploymentPlan(
        run_id=run_id,
        core_node=core_node,
        ran_node=ran_node,
        radio=radio,
        radio_intent=radio_intent or r2lab_oai_aligned_candidate(),
        tx_gain_db=tx_gain_db,
        rx_gain_db=rx_gain_db,
    ).validate()
