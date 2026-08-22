from __future__ import annotations

import unittest

from synthran.r2lab.radio import (
    ArfcnSemantic,
    NrArfcn,
    PhysicalRadioProfile,
    R2LAB_OAI_BAND78_REFERENCE,
    R2LabRadioProfileError,
    ReferenceAlignedPhysicalIntent,
    derive_carrier_center_from_reference,
    nominal_bandwidth_mhz,
    r2lab_oai_aligned_candidate,
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

    def test_reference_grid_derives_distinct_carrier_center(self) -> None:
        carrier = derive_carrier_center_from_reference(R2LAB_OAI_BAND78_REFERENCE)
        self.assertEqual(ArfcnSemantic.CARRIER_CENTER, carrier.semantic)
        self.assertEqual(621_984, carrier.value)
        self.assertAlmostEqual(3329.76, carrier.frequency_mhz)
        self.assertNotEqual(R2LAB_OAI_BAND78_REFERENCE.ssb.value, carrier.value)

    def test_reference_grid_maps_to_nominal_60mhz_profile(self) -> None:
        self.assertEqual(60, nominal_bandwidth_mhz(R2LAB_OAI_BAND78_REFERENCE))
        intent = r2lab_oai_aligned_candidate()
        self.assertEqual(60, intent.profile.channel_bandwidth_mhz)
        self.assertEqual(2, intent.profile.nof_antennas_dl)
        self.assertEqual(2, intent.profile.nof_antennas_ul)
        self.assertEqual(
            "offline-reference-aligned-candidate",
            intent.to_dict()["acceptance"],
        )

    def test_reference_alignment_rejects_smoke002_ssb_as_carrier(self) -> None:
        intent = ReferenceAlignedPhysicalIntent(
            profile=PhysicalRadioProfile(
                band=78,
                carrier=NrArfcn(621_312, ArfcnSemantic.CARRIER_CENTER),
                channel_bandwidth_mhz=60,
                common_scs_khz=30,
                nof_antennas_dl=2,
                nof_antennas_ul=2,
            ),
            expected_ssb=R2LAB_OAI_BAND78_REFERENCE.ssb,
            reference=R2LAB_OAI_BAND78_REFERENCE,
        )
        with self.assertRaisesRegex(R2LabRadioProfileError, "carrier center"):
            intent.validate()

    def test_reference_alignment_rejects_narrow_or_siso_candidate(self) -> None:
        carrier = derive_carrier_center_from_reference(R2LAB_OAI_BAND78_REFERENCE)
        narrow = ReferenceAlignedPhysicalIntent(
            profile=PhysicalRadioProfile(
                band=78,
                carrier=carrier,
                channel_bandwidth_mhz=20,
                common_scs_khz=30,
                nof_antennas_dl=2,
                nof_antennas_ul=2,
            ),
            expected_ssb=R2LAB_OAI_BAND78_REFERENCE.ssb,
            reference=R2LAB_OAI_BAND78_REFERENCE,
        )
        with self.assertRaisesRegex(R2LabRadioProfileError, "bandwidth"):
            narrow.validate()

        siso = ReferenceAlignedPhysicalIntent(
            profile=PhysicalRadioProfile(
                band=78,
                carrier=carrier,
                channel_bandwidth_mhz=60,
                common_scs_khz=30,
                nof_antennas_dl=1,
                nof_antennas_ul=1,
            ),
            expected_ssb=R2LAB_OAI_BAND78_REFERENCE.ssb,
            reference=R2LAB_OAI_BAND78_REFERENCE,
        )
        with self.assertRaisesRegex(R2LabRadioProfileError, "antenna"):
            siso.validate()


if __name__ == "__main__":
    unittest.main()
