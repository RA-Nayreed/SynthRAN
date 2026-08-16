from __future__ import annotations

import unittest

from synthran.phase3_render import render_cooja_scenario, render_generated_header
from synthran.phase3_runtime import Phase3Scenario


class Phase3RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = Phase3Scenario(
            "phase3-01",
            "acceptance-20260815-05",
            "12.1.0.1",
            cooja_seed=424242,
            serial_socket_port=60001,
        )

    def test_generated_header_is_run_scoped(self) -> None:
        header = render_generated_header(self.scenario)
        self.assertIn('#define SYNTHRAN_RUN_ID "phase3-01"', header)
        self.assertIn('#define SYNTHRAN_EDGE_BROKER_IPV6 "fd00::1"', header)
        self.assertIn("SYNTHRAN_SENSOR_PERIOD_SECONDS 10", header)

    def test_cooja_scenario_has_one_br_and_ten_sensors(self) -> None:
        csc = render_cooja_scenario(self.scenario)
        self.assertIn("<randomseed>424242</randomseed>", csc)
        self.assertIn("<port>60001</port>", csc)
        self.assertIn("SerialSocketServer", csc)
        self.assertIn("TIMEOUT(86400000)", csc)
        self.assertEqual(csc.count("<identifier>synthran-br</identifier>"), 1)
        self.assertEqual(csc.count("<identifier>synthran-sensor</identifier>"), 1)
        for sensor_id in range(1, 11):
            self.assertIn(f"<id>{sensor_id}</id>", csc)
        self.assertIn("<id>250</id>", csc)
        self.assertEqual(csc.count("<mote>"), 11)


if __name__ == "__main__":
    unittest.main()
