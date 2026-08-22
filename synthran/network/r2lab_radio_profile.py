"""Offline semantic validation for physical R2Lab radio profiles.

Live smoke 002 showed that copying an OAI SSB ARFCN into srsRAN's carrier ARFCN
field is not a faithful configuration translation. This module keeps frequency
*meaning* attached to every ARFCN so a physical profile cannot silently reuse a
value observed in a different semantic field.

It deliberately does not claim a new accepted srsRAN carrier profile. A profile
can be proven *reference aligned* offline, but it remains a candidate until the
rendered srsRAN configuration is inspected and later validated live.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class R2LabRadioProfileError(ValueError):
    """Raised when a physical radio profile is semantically unsafe."""


class ArfcnSemantic(str, Enum):
    """Meaning carried by one NR-ARFCN value."""

    CARRIER_CENTER = "carrier-center"
    SSB = "ssb"
    POINT_A = "point-a"


@dataclass(frozen=True)
class NrArfcn:
    value: int
    semantic: ArfcnSemantic

    def __post_init__(self) -> None:
        if self.value < 0 or self.value > 3_279_165:
            raise R2LabRadioProfileError("NR-ARFCN is outside the global raster")

    @property
    def frequency_mhz(self) -> float:
        """Convert NR-ARFCN to reference frequency using the global raster."""

        n = self.value
        if n < 600_000:
            return n * 0.005
        if n < 2_016_667:
            return 3000.0 + (n - 600_000) * 0.015
        return 24_250.08 + (n - 2_016_667) * 0.060

    def to_dict(self) -> dict[str, object]:
        return {
            "arfcn": self.value,
            "semantic": self.semantic.value,
            "frequency_mhz": self.frequency_mhz,
        }


@dataclass(frozen=True)
class PhysicalRadioProfile:
    """A candidate physical srsRAN carrier profile, validated offline only."""

    band: int
    carrier: NrArfcn
    channel_bandwidth_mhz: int
    common_scs_khz: int
    nof_antennas_dl: int
    nof_antennas_ul: int

    def validate(self) -> "PhysicalRadioProfile":
        if self.band != 78:
            raise R2LabRadioProfileError("current R2Lab N300 checkpoint accepts band 78 only")
        if self.carrier.semantic is not ArfcnSemantic.CARRIER_CENTER:
            raise R2LabRadioProfileError(
                "physical srsRAN dl_arfcn requires a carrier-center ARFCN; "
                f"received {self.carrier.semantic.value} semantics"
            )
        if self.channel_bandwidth_mhz not in {10, 20, 30, 40, 50, 60, 70, 80, 90, 100}:
            raise R2LabRadioProfileError("unsupported FR1 channel bandwidth")
        if self.common_scs_khz not in {15, 30, 60}:
            raise R2LabRadioProfileError("unsupported FR1 common subcarrier spacing")
        if not 1 <= self.nof_antennas_dl <= 4:
            raise R2LabRadioProfileError("downlink antenna count must be between 1 and 4")
        if not 1 <= self.nof_antennas_ul <= 4:
            raise R2LabRadioProfileError("uplink antenna count must be between 1 and 4")
        return self

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "band": self.band,
            "carrier": self.carrier.to_dict(),
            "channel_bandwidth_mhz": self.channel_bandwidth_mhz,
            "common_scs_khz": self.common_scs_khz,
            "nof_antennas_dl": self.nof_antennas_dl,
            "nof_antennas_ul": self.nof_antennas_ul,
            "acceptance": "offline-candidate-only",
        }


@dataclass(frozen=True)
class OaiRadioReference:
    """Sanitized semantic fields observed in an R2Lab OAI reference config."""

    ssb: NrArfcn
    point_a: NrArfcn
    carrier_prbs: int
    subcarrier_spacing_khz: int
    tx_paths: int
    rx_paths: int

    def __post_init__(self) -> None:
        if self.ssb.semantic is not ArfcnSemantic.SSB:
            raise R2LabRadioProfileError("OAI SSB reference must retain SSB semantics")
        if self.point_a.semantic is not ArfcnSemantic.POINT_A:
            raise R2LabRadioProfileError("OAI Point A reference must retain Point A semantics")
        if self.carrier_prbs <= 0:
            raise R2LabRadioProfileError("carrier PRB count must be positive")
        if self.subcarrier_spacing_khz <= 0:
            raise R2LabRadioProfileError("subcarrier spacing must be positive")
        if self.tx_paths <= 0 or self.rx_paths <= 0:
            raise R2LabRadioProfileError("radio path counts must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "ssb": self.ssb.to_dict(),
            "point_a": self.point_a.to_dict(),
            "carrier_prbs": self.carrier_prbs,
            "subcarrier_spacing_khz": self.subcarrier_spacing_khz,
            "tx_paths": self.tx_paths,
            "rx_paths": self.rx_paths,
        }


# FR1 nominal channel bandwidths for the reference-grid combinations that this
# checkpoint needs to reason about.  The live reference uses 162 PRBs at 30 kHz,
# which corresponds to a nominal 60 MHz carrier.
_NOMINAL_BANDWIDTH_MHZ = {
    (15, 52): 10,
    (15, 106): 20,
    (15, 160): 30,
    (15, 216): 40,
    (15, 270): 50,
    (30, 24): 10,
    (30, 51): 20,
    (30, 78): 30,
    (30, 106): 40,
    (30, 133): 50,
    (30, 162): 60,
    (30, 189): 70,
    (30, 217): 80,
    (30, 245): 90,
    (30, 273): 100,
}


def nominal_bandwidth_mhz(reference: OaiRadioReference) -> int:
    """Return nominal FR1 bandwidth for one explicit OAI resource-grid pair."""

    try:
        return _NOMINAL_BANDWIDTH_MHZ[
            (reference.subcarrier_spacing_khz, reference.carrier_prbs)
        ]
    except KeyError as exc:
        raise R2LabRadioProfileError(
            "reference PRB/SCS pair is not supported by the physical checkpoint"
        ) from exc


def derive_carrier_center_from_reference(reference: OaiRadioReference) -> NrArfcn:
    """Derive the resource-grid center ARFCN from Point A for offline review.

    For the current FR1 raster, one NR-ARFCN step above 3 GHz is 15 kHz. Point A
    is the reference frequency for the lowest subcarrier of common RB 0, so the
    center of an ``N_RB`` resource grid is half of ``N_RB * 12 * SCS`` above it.
    The result is explicitly tagged as carrier-center semantics and is still only
    an offline candidate.
    """

    point_a = reference.point_a
    if point_a.value < 600_000 or point_a.value >= 2_016_667:
        raise R2LabRadioProfileError(
            "current R2Lab carrier-center derivation supports the FR1 15 kHz raster only"
        )
    occupied_khz = reference.carrier_prbs * 12 * reference.subcarrier_spacing_khz
    half_khz = occupied_khz / 2
    steps = half_khz / 15
    if not steps.is_integer():
        raise R2LabRadioProfileError(
            "reference resource-grid center does not land on the NR-ARFCN raster"
        )
    return NrArfcn(point_a.value + int(steps), ArfcnSemantic.CARRIER_CENTER)


@dataclass(frozen=True)
class ReferenceAlignedPhysicalIntent:
    """Offline proof that a candidate preserves the semantics of one reference."""

    profile: PhysicalRadioProfile
    expected_ssb: NrArfcn
    reference: OaiRadioReference

    def validate(self) -> "ReferenceAlignedPhysicalIntent":
        self.profile.validate()
        if self.expected_ssb.semantic is not ArfcnSemantic.SSB:
            raise R2LabRadioProfileError("expected SSB must retain SSB semantics")
        if self.expected_ssb.value != self.reference.ssb.value:
            raise R2LabRadioProfileError("candidate SSB does not match the reviewed reference")

        derived_carrier = derive_carrier_center_from_reference(self.reference)
        if self.profile.carrier.value != derived_carrier.value:
            raise R2LabRadioProfileError(
                "candidate carrier center does not align with the reviewed Point-A resource grid"
            )
        if self.profile.channel_bandwidth_mhz != nominal_bandwidth_mhz(self.reference):
            raise R2LabRadioProfileError(
                "candidate nominal bandwidth does not match the reviewed reference grid"
            )
        if self.profile.common_scs_khz != self.reference.subcarrier_spacing_khz:
            raise R2LabRadioProfileError(
                "candidate common SCS does not match the reviewed reference"
            )
        if self.profile.nof_antennas_dl != self.reference.tx_paths:
            raise R2LabRadioProfileError(
                "candidate downlink antenna count does not match the reviewed reference"
            )
        if self.profile.nof_antennas_ul != self.reference.rx_paths:
            raise R2LabRadioProfileError(
                "candidate uplink antenna count does not match the reviewed reference"
            )
        return self

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "profile": self.profile.to_dict(),
            "expected_ssb": self.expected_ssb.to_dict(),
            "reference": self.reference.to_dict(),
            "derived_carrier_center": derive_carrier_center_from_reference(
                self.reference
            ).to_dict(),
            "reference_nominal_bandwidth_mhz": nominal_bandwidth_mhz(self.reference),
            "acceptance": "offline-reference-aligned-candidate",
        }


R2LAB_OAI_BAND78_REFERENCE = OaiRadioReference(
    ssb=NrArfcn(621_312, ArfcnSemantic.SSB),
    point_a=NrArfcn(620_040, ArfcnSemantic.POINT_A),
    carrier_prbs=162,
    subcarrier_spacing_khz=30,
    tx_paths=2,
    rx_paths=2,
)


def r2lab_oai_aligned_candidate() -> ReferenceAlignedPhysicalIntent:
    """Build the conservative offline candidate implied by the reviewed OAI grid.

    This helper exists so future deployment code cannot accidentally reconstruct
    the smoke-002 SSB-as-carrier mistake.  Its output is not live acceptance.
    """

    return ReferenceAlignedPhysicalIntent(
        profile=PhysicalRadioProfile(
            band=78,
            carrier=derive_carrier_center_from_reference(R2LAB_OAI_BAND78_REFERENCE),
            channel_bandwidth_mhz=nominal_bandwidth_mhz(R2LAB_OAI_BAND78_REFERENCE),
            common_scs_khz=R2LAB_OAI_BAND78_REFERENCE.subcarrier_spacing_khz,
            nof_antennas_dl=R2LAB_OAI_BAND78_REFERENCE.tx_paths,
            nof_antennas_ul=R2LAB_OAI_BAND78_REFERENCE.rx_paths,
        ),
        expected_ssb=R2LAB_OAI_BAND78_REFERENCE.ssb,
        reference=R2LAB_OAI_BAND78_REFERENCE,
    ).validate()
