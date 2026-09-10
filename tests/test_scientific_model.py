from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import simpy
import yaml

from synthran.ambient_iot.config import TraceEnergySource, energy_sources
from synthran.ambient_iot.protocols import adaptive_aloha
from synthran.ambient_iot.runner import AmbientIoTRunner
from synthran.ambient_iot.bridge import decoded_events
from synthran.model.capacitor import Capacitor, CapacitorParams
from synthran.model.packet_analysis import apply_sic
from synthran.model.receiver import decode_receptions
from synthran.model.propagation import urban_macro_loss_db_38_901
from synthran.scenario import load_scenario, remap_gateways


def scenario(duration=1000):
    return {
        "deployment": {
            "core": "open5gs",
            "ran": "srsran",
            "platform": "rfsim",
            "ues": ["gateway", "background"],
        },
        "model": {
            "seed": 12,
            "duration_ms": duration,
            "energy": {"mode": "always_powered", "constant_power_w": 0},
            "capacitor": {"initial_voltage_v": 2},
            "controller": {"max_startup_time_ms": 0},
            "topology": {
                "base_station": {
                    "sectors": [
                        {"azimuth_deg": 0, "beamwidth_deg": 360, "power_dbm": 46}
                    ]
                }
            },
            "propagation": {"model": "fspl"},
            "protocol": {"type": "unicast", "rx_duration_ms": 5},
            "receiver": {"bandwidth_hz": 100000, "required_sinr_db": 3, "sic": True},
        },
        "mqtt": {"payload_bytes": 256},
        "devices": {
            "sensor": {
                "gateway": "gateway",
                "x": 0,
                "y": 15,
                "sensing_interval_ms": 100,
                "sensing_phase_ms": 0,
            }
        },
    }


class EnergyTests(unittest.TestCase):
    def test_csv_timestamps_interpolation_units_and_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "energy.csv"
            path.write_text("time_s,power_uw\n0,10\n10,20\n20,30\n")
            env = simpy.Environment()
            hold = TraceEnergySource(env, {"trace": str(path), "interpolation": "hold"})
            linear = TraceEnergySource(
                env, {"trace": str(path), "interpolation": "linear", "repeat": False}
            )
            env.run(until=1.5)
            self.assertAlmostEqual(hold.ext_power, 10e-6)
            self.assertAlmostEqual(linear.power_at(5), 15e-6)
            self.assertAlmostEqual(hold.power_at(25), 30e-6)
            self.assertAlmostEqual(hold.power_at(30), 10e-6)
            self.assertAlmostEqual(linear.power_at(100), 30e-6)

    def test_invalid_trace_is_rejected(self):
        for times, values in [
            ([0, 0], [1, 2]),
            ([1], [1]),
            ([0], [-1]),
            ([0], [float("nan")]),
        ]:
            with (
                self.subTest(times=times, values=values),
                self.assertRaises(ValueError),
            ):
                TraceEnergySource(simpy.Environment(), {}, series=(times, values))

    def test_common_and_independent_sources_are_repeatable(self):
        config = {"source": "lognormal", "mean_power_w": 0.001, "correlation": "common"}
        names = {0: "a", 1: "b"}
        devices = {name: {} for name in names.values()}
        common = energy_sources(
            simpy.Environment(), config, devices, names, 10000, 44, None
        )
        self.assertTrue(np.array_equal(common[0].values, common[1].values))
        config["correlation"] = "independent"
        independent = energy_sources(
            simpy.Environment(), config, devices, names, 10000, 44, None
        )
        repeated = energy_sources(
            simpy.Environment(), config, devices, names, 10000, 44, None
        )
        self.assertFalse(np.array_equal(independent[0].values, independent[1].values))
        self.assertTrue(np.array_equal(independent[0].values, repeated[0].values))

    def test_csv_copies_are_not_called_independent(self):
        with self.assertRaises(ValueError):
            energy_sources(
                simpy.Environment(),
                {"correlation": "independent"},
                {"a": {}},
                {0: "a"},
                1000,
                1,
                None,
            )

    def test_wpt_control_changes_harvesting_without_changing_the_link(self):
        base = scenario(100)
        base["model"]["energy"] = {
            "mode": "wpt",
            "constant_power_w": 0,
            "wpt_power_w": 0,
        }
        base["model"]["capacitor"]["initial_voltage_v"] = 0
        off = AmbientIoTRunner(base).run()
        base["model"]["energy"]["wpt_power_w"] = 0.1
        powered = AmbientIoTRunner(base).run()
        self.assertEqual(off["capacitors"][0].voltage, 0)
        self.assertGreater(powered["capacitors"][0].voltage, 0)
        self.assertEqual(off["downlink"], powered["downlink"])
        self.assertEqual(off["uplink"], powered["uplink"])


class CapacitorTests(unittest.TestCase):
    def make(self, **kwargs):
        return Capacitor(simpy.Environment(), 0, **kwargs)

    def test_zero_load_modes_and_exact_circuit_solution(self):
        first, second = self.make(initial_voltage=1), self.make(initial_voltage=1)
        first.voltage_source = second.voltage_source = 2
        first.capacitor_charging()
        second.charge_and_discharge(0)
        conductance = 1 / 5000 + 1 / 100000
        equilibrium = (2 / 5000) / conductance
        expected = equilibrium + (1 - equilibrium) * math.exp(
            -conductance * 0.001 / 0.0003
        )
        self.assertAlmostEqual(first.voltage, second.voltage, places=14)
        self.assertAlmostEqual(first.voltage, expected, places=14)

    def test_diode_blocks_backflow_and_energy_balances_at_boundaries(self):
        cap = self.make(initial_voltage=1, params=CapacitorParams(dt=0.1))
        for source, load in [(0, 0), (5, 0), (5, 0), (5, 0), (0.5, 0.003), (0, 0.01)]:
            cap.voltage_source = source
            cap.advance(load)
        balance = (
            cap.initial_energy
            + cap.energy_account["source_j"]
            - sum(
                value for key, value in cap.energy_account.items() if key != "source_j"
            )
        )
        self.assertAlmostEqual(balance, cap.energy, places=11)
        self.assertGreaterEqual(cap.voltage, 0)
        self.assertLessEqual(cap.voltage, cap.voltage_max)

    def test_leakage_and_step_refinement(self):
        for step in [0.01, 0.001]:
            cap = self.make(initial_voltage=1, params=CapacitorParams(dt=step))
            for _ in range(round(1 / step)):
                cap.capacitor_charging()
            self.assertAlmostEqual(
                cap.voltage, math.exp(-1 / (100000 * 0.0003)), places=12
            )
            self.assertAlmostEqual(cap.internal_time, 1, places=12)


class ReceiverTests(unittest.TestCase):
    def packet(self, power, start=0, end=5, **kwargs):
        return {
            "rssi_dbm": power,
            "start_ms": start,
            "end_ms": end,
            "sensitivity_dbm": -120,
            "energy_complete": True,
            **kwargs,
        }

    def test_residual_power_controls_sic(self):
        for factor, expected in [
            (0, [0]),
            (0.5, [0]),
            (0.9, [0]),
            (0.99, [0, 1]),
            (1, [0, 1]),
        ]:
            with self.subTest(factor=factor):
                self.assertEqual(apply_sic([-40, -50], 1e-12, 3, factor)[0], expected)
                result = decode_receptions(
                    [self.packet(-40), self.packet(-50)], 1e-12, 3, factor
                )
                self.assertEqual(
                    [
                        i
                        for i, row in enumerate(result)
                        if row["decode_stage"] is not None
                    ],
                    expected,
                )
        self.assertEqual(result[1]["outcome"], "sic_recovered")

    def test_singleton_sinr_and_touching_intervals(self):
        result = decode_receptions([self.packet(-100)], 1e-10, 3, 1)
        self.assertEqual(result[0]["outcome"], "below_sinr")
        result = decode_receptions(
            [self.packet(-40, 0, 1), self.packet(-50, 1, 2)], 1e-12, 3, 0
        )
        self.assertEqual([row["outcome"] for row in result], ["decoded", "decoded"])

    def test_failed_energy_packet_interferes_without_being_decoded(self):
        result = decode_receptions(
            [self.packet(-40, energy_complete=False), self.packet(-50)], 1e-12, 3, 1
        )
        self.assertEqual(result[0]["outcome"], "energy_interrupted")
        self.assertIsNone(result[1]["decode_stage"])

    def test_frame_local_observations_drive_adaptation(self):
        bs = SimpleNamespace(
            slot_outcomes_this_frame=[],
            rx_packets=[SimpleNamespace(collided=True)] * 10000,
        )
        policy = adaptive_aloha({"slots": 8})(bs)
        self.assertEqual(len(next(policy)) - 1, 8)
        bs.slot_outcomes_this_frame = ["idle"] * 8
        self.assertEqual(len(next(policy)) - 1, 4)
        bs.slot_outcomes_this_frame = ["occupied_undecoded"] * 4
        self.assertEqual(len(next(policy)) - 1, 8)

    def test_uma_lower_domain_has_no_discontinuity(self):
        self.assertEqual(
            urban_macro_loss_db_38_901(9, 924e6), urban_macro_loss_db_38_901(10, 924e6)
        )


class ControllerTests(unittest.TestCase):
    def test_registration_and_energy_horizon(self):
        config = scenario(1000.25)
        config["model"]["protocol"]["pre_registered"] = False
        result = AmbientIoTRunner(config).run()
        self.assertGreater(result["backscatter_modules"][0].acks_received, 0)
        self.assertGreater(len(decoded_events(result, config)), 0)
        self.assertAlmostEqual(
            result["capacitors"][0].internal_time, 1.00025, places=12
        )

    def test_interactive_gateway_selection_preserves_the_sensor_cohort(self):
        config = scenario()
        config["devices"].update(
            {f"sensor{i}": {"gateway": "gateway"} for i in range(10)}
        )
        remap_gateways(config, ["qhat01", "qhat02"])
        self.assertEqual(len(config["devices"]), 11)
        self.assertTrue(
            all(device["gateway"] == "qhat01" for device in config["devices"].values())
        )
        config["devices"]["background-sensor"] = {"gateway": "qhat02"}
        with self.assertRaises(ValueError):
            remap_gateways(config, ["qhat01"])

    def test_protocol_duration_and_slot_limits_fail_before_execution(self):
        for protocol in [
            {"type": "broadcast", "slots": 0},
            {"type": "unicast", "rx_duration_ms": 0},
            {"type": "adaptive_aloha", "min_slots": 8, "max_slots": 4},
            {"schedule": []},
        ]:
            config = scenario()
            config["model"]["protocol"] = protocol
            with self.subTest(protocol=protocol), self.assertRaises(ValueError):
                AmbientIoTRunner(config).run()

    def test_sensing_period_and_fractional_phase_are_effective(self):
        for period, count in [(100, 10), (250, 4)]:
            config = scenario()
            config["devices"]["sensor"].update(
                sensing_interval_ms=period, sensing_phase_ms=10.25
            )
            result = AmbientIoTRunner(config).run()
            generated = [
                row
                for row in result["controllers"][0].events
                if row["kind"] == "generated"
            ]
            self.assertEqual(len(generated), count)
            self.assertTrue(
                np.allclose(
                    [row["generated_ms"] for row in generated],
                    [12.25 + period * i for i in range(count)],
                )
            )
            events = decoded_events(result, config)
            self.assertGreater(len(events), 0)
            self.assertTrue(
                all(
                    event["generated_time_s"]
                    <= event["decode_time_s"]
                    == event["time_offset_s"]
                    for event in events
                )
            )
            self.assertTrue(
                all(len(event["payload"].encode()) == 256 for event in events)
            )

    def test_mid_transmission_brownout_cannot_produce_a_decode(self):
        config = scenario(100)
        config["model"]["energy"]["mode"] = "environmental"
        config["model"]["capacitor"].update(
            capacitance_f=1e-5, leakage_resistance_ohm=float("inf")
        )
        config["model"]["controller"]["currents_a"] = {
            "listening": 0,
            "sensing": 0,
            "processing": 0,
            "transmitting": 0.005,
        }
        result = AmbientIoTRunner(config).run()
        self.assertEqual(decoded_events(result, config), [])
        self.assertTrue(
            any(
                not packet.energy_complete
                for packet in result["backscatter_modules"][0].tx_records
            )
        )
        self.assertTrue(
            any(
                packet.outcome == "energy_interrupted"
                for packet in result["bs_behavior"].rx_packets
            )
        )

    def test_unpowered_sensor_does_not_receive_commands(self):
        config = scenario(100)
        config["model"]["energy"]["mode"] = "environmental"
        config["model"]["capacitor"]["initial_voltage_v"] = 0
        result = AmbientIoTRunner(config).run()
        self.assertEqual(result["backscatter_modules"][0].rx_records, [])
        self.assertEqual(result["controllers"][0].data_history, [])

    def test_airtime_longer_than_slot_is_rejected(self):
        config = scenario()
        config["model"]["controller"]["durations_ms"] = {"transmitting": 6}
        with self.assertRaises(ValueError):
            AmbientIoTRunner(config).run()

    def test_sensor_population_does_not_follow_gateway_count(self):
        config = scenario()
        config["devices"].update(
            {f"sensor{i}": {"gateway": "gateway"} for i in range(10)}
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.yml"
            path.write_text(yaml.safe_dump(config))
            loaded = load_scenario(path)
            self.assertEqual(len(loaded["devices"]), 11)
            self.assertEqual(len(loaded["deployment"]["ues"]), 2)
            config["devices"]["unmapped"] = {}
            path.write_text(yaml.safe_dump(config))
            with self.assertRaises(ValueError):
                load_scenario(path)


if __name__ == "__main__":
    unittest.main()
