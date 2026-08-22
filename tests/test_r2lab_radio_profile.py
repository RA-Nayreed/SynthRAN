from __future__ import annotations

import unittest

from synthran.network.r2lab_radio_profile import (
    ArfcnSemantic,
    NrArfcn,
    PhysicalRadioProfile,
    R2LAB_OAI_BAND78_REFERENCE,
    R2LabRadioProfileError,
)


class R2LabRadioProfileTests(unittest.TestCase):
    def test_reference_arfcn_frequencies_match_recorded_oai_semantics(self) -> None:
        self.assertAlmostEqual(3319.68, R2LAB_OAI_BAND78_REFERENCE.ssb.frequency_mhz)
        self.assertAlmostEqual(3300.60, R2LAB_OAI_BAND78_REFERENCE.point_a.frequency_mhz)
        self.assertEqual(162, R2LAB_OAI_BAND78_REFERENCE.carrier_prbs)
        self.assertEqual(30, R2LAB_OAI_BAND78_REFERENCE.subcarrier_spacing_khz)
        self.assertEqual(2, R2LAB_OAI_BAND78_REFERENCE.tx_paths)
        self.assertEqual(2, R2LAB_OAI_BAND78_REFERENCE.rx_paths)

    def test_ssb_semantics_cannot_be_silently_used_as_carrier_arfcn(self) -> None:
        profile = PhysicalRadioProfile(
            band=78,
            carrier=R2LAB_OAI_BAND78_REFERENCE.ssb,
            channel_bandwidth_mhz=20,
            common_scs_khz=30,
            nof_antennas_dl=1,
            nof_antennas_ul=1,
        )
        with self.assertRaises(R2LabRadioProfileError):
            profile.validate()

    def test_point_a_semantics_cannot_be_silently_used_as_carrier_arfcn(self) -> None:
        profile = PhysicalRadioProfile(
            band=78,
            carrier=R2LAB_OAI_BAND78_REFERENCE.point_a,
            channel_bandwidth_mhz=60,
            common_scs_khz=30,
            nof_antennas_dl=2,
            nof_antennas_ul=2,
        )
        with self.assertRaises(R2LabRadioProfileError):
            profile.validate()

    def test_explicit_carrier_semantics_are_required_for_candidate_profile(self) -> None:
        profile = PhysicalRadioProfile(
            band=78,
            carrier=NrArfcn(621_984, ArfcnSemantic.CARRIER_CENTER),
            channel_bandwidth_mhz=60,
            common_scs_khz=30,
            nof_antennas_dl=2,
            nof_antennas_ul=2,
        ).validate()
        payload = profile.to_dict()
        self.assertEqual("carrier-center", payload["carrier"]["semantic"])
        self.assertEqual("offline-candidate-only", payload["acceptance"])

    def test_candidate_profile_does_not_claim_live_acceptance(self) -> None:
        profile = PhysicalRadioProfile(
            band=78,
            carrier=NrArfcn(621_984, ArfcnSemantic.CARRIER_CENTER),
            channel_bandwidth_mhz=60,
            common_scs_khz=30,
            nof_antennas_dl=2,
            nof_antennas_ul=2,
        )
        self.assertEqual("offline-candidate-only", profile.to_dict()["acceptance"])

    def test_global_nr_arfcn_raster_conversion_for_fr1(self) -> None:
        self.assertAlmostEqual(
            3600.0,
            NrArfcn(640_000, ArfcnSemantic.CARRIER_CENTER).frequency_mhz,
        )
        self.assertAlmostEqual(
            3405.0,
            NrArfcn(627_000, ArfcnSemantic.CARRIER_CENTER).frequency_mhz,
        )


if __name__ == "__main__":
    unittest.main()
