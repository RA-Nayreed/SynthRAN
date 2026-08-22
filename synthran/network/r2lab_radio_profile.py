"""Offline semantic validation for physical R2Lab radio profiles.

Live smoke 002 showed that copying an OAI SSB ARFCN into srsRAN's carrier ARFCN
field is not a faithful configuration translation. This module keeps frequency
*meaning* attached to every ARFCN so a physical profile cannot silently reuse a
value observed in a different semantic field.

It deliberately does not derive a new accepted srsRAN carrier profile. The next
carrier/SSB plan remains a candidate until its rendered srsRAN output is reviewed
and later validated live.
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


R2LAB_OAI_BAND78_REFERENCE = OaiRadioReference(
    ssb=NrArfcn(621_312, ArfcnSemantic.SSB),
    point_a=NrArfcn(620_040, ArfcnSemantic.POINT_A),
    carrier_prbs=162,
    subcarrier_spacing_khz=30,
    tx_paths=2,
    rx_paths=2,
)
