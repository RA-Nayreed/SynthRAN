from __future__ import annotations

import unittest

from synthran.r2lab.radio import (
    CellAcquisitionState,
    Ipv4State,
    PacketServiceState,
    QfitRuntimeEvidence,
    RegistrationState,
    parse_c5greg,
    parse_ipv4_state,
    parse_packet_service,
    parse_qnwinfo,
)


class R2LabQfitRuntimeTests(unittest.TestCase):
    def test_smoke002_no_service_state_does_not_advance_acceptance(self) -> None:
        evidence = QfitRuntimeEvidence(
            cell=parse_qnwinfo('+QNWINFO: "No Service"\nOK\n'),
            registration=parse_c5greg('+C5GREG: 0,0\nOK\n'),
            packet_service=parse_packet_service("Packet service state: 'detached'\n"),
            ipv4=parse_ipv4_state(""),
        )

        self.assertEqual(CellAcquisitionState.NO_SERVICE, evidence.cell)
        self.assertEqual(RegistrationState.NOT_REGISTERED, evidence.registration)
        self.assertEqual(PacketServiceState.DETACHED, evidence.packet_service)
        self.assertEqual(Ipv4State.ABSENT, evidence.ipv4)
        self.assertFalse(evidence.cell_acquired)
        self.assertFalse(evidence.registered)
        self.assertFalse(evidence.pdu_session_established)

    def test_nr_sa_registration_and_packet_state_are_separate_gates(self) -> None:
        acquired = QfitRuntimeEvidence(
            cell=parse_qnwinfo('+QNWINFO: "NR5G-SA","00101","NR5G BAND 78",621312\n'),
            registration=parse_c5greg('+C5GREG: 0,2\n'),
            packet_service=parse_packet_service("Packet service state: 'detached'\n"),
            ipv4=parse_ipv4_state(""),
        )
        self.assertTrue(acquired.cell_acquired)
        self.assertFalse(acquired.registered)
        self.assertFalse(acquired.pdu_session_established)

        registered = QfitRuntimeEvidence(
            cell=acquired.cell,
            registration=parse_c5greg('+C5GREG: 0,1\n'),
            packet_service=acquired.packet_service,
            ipv4=acquired.ipv4,
        )
        self.assertTrue(registered.registered)
        self.assertFalse(registered.pdu_session_established)

    def test_attached_plus_ipv4_is_pdu_evidence_but_not_user_plane(self) -> None:
        evidence = QfitRuntimeEvidence(
            cell=parse_qnwinfo('+QNWINFO: "NR5G-SA","00101","NR5G BAND 78",621312\n'),
            registration=parse_c5greg('+C5GREG: 0,1\n'),
            packet_service=parse_packet_service("Packet service state: 'attached'\n"),
            ipv4=parse_ipv4_state(
                "9: wwan0    inet 198.51.100.2/24 scope global wwan0\n"
            ),
        )
        self.assertTrue(evidence.pdu_session_established)
        self.assertEqual("requires-separate-traffic-probe", evidence.to_dict()["user_plane"])

    def test_conflicting_registration_or_packet_state_stays_unknown(self) -> None:
        self.assertEqual(
            RegistrationState.UNKNOWN,
            parse_c5greg('+C5GREG: 0,2\n+C5GREG: 0,1\n'),
        )
        self.assertEqual(
            PacketServiceState.UNKNOWN,
            parse_packet_service(
                "Packet service state: 'detached'\nPacket service state: 'attached'\n"
            ),
        )

    def test_missing_interface_is_unknown_not_clean(self) -> None:
        self.assertEqual(
            Ipv4State.UNKNOWN,
            parse_ipv4_state("", interface_present=False),
        )


if __name__ == "__main__":
    unittest.main()
