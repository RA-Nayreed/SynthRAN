"""Build and execute SynthRAN's native Ambient-IoT model."""

from __future__ import annotations

import random
import warnings
from typing import Any

import numpy as np
import simpy
from synthran.model import (
    backscatter,
    bsengine,
    capacitor,
    controller,
    propagation,
    radiodevices,
)

from .config import duration_ms, energy_sources, threshold
from .protocols import resolve


class AmbientIoTRunner:
    """Turn a SynthRAN scenario into native Ambient-IoT simulation objects."""

    def __init__(self, scenario: dict[str, Any]):
        self.scenario = scenario
        self.model = scenario["model"]
        if str(self.model.get("engine", "ambient_iot")).lower() != "ambient_iot":
            raise ValueError("model.engine must be ambient_iot")

    def run(self) -> dict[str, Any]:
        seed = int(self.model.get("seed", 1))
        env = simpy.Environment()
        nodes, names = self._nodes(seed)
        base_stations = self._base_stations()
        energy_config = self.model.get("energy", {})
        sources = energy_sources(
            env,
            energy_config,
            self.scenario["devices"],
            names,
            duration_ms(self.model),
            seed,
            self.scenario.get("_source_directory"),
        )
        wpt_power = energy_config.get("wpt_power_w")
        if wpt_power is not None and (
            not np.isfinite(float(wpt_power)) or float(wpt_power) < 0
        ):
            raise ValueError("wpt_power_w must be finite and nonnegative")
        if str(energy_config.get("mode", "hybrid")).lower() not in {
            "wpt",
            "environmental",
            "external",
            "hybrid",
            "always_powered",
        }:
            raise ValueError("unsupported energy mode")
        mode = str(energy_config.get("mode", "hybrid")).lower()
        coverage = propagation.CoverageMap(
            base_stations=base_stations,
            nodes=nodes,
            freq_hz=float(
                self.model.get("propagation", self.model.get("topology", {})).get(
                    "frequency_hz", 924e6
                )
            ),
            pathloss_model=str(
                self.model.get("propagation", {}).get(
                    "model", self.model.get("topology", {}).get("pathloss", "macro")
                )
            ),
            los=bool(self.model.get("propagation", {}).get("los", True)),
            extra_np_per_m=float(
                self.model.get("propagation", {}).get("extra_np_per_m", 0)
            ),
            bandwidth_hz=float(
                self.model.get("receiver", {}).get("bandwidth_hz", 100e6)
            ),
            noise_figure_db=float(
                self.model.get("receiver", {}).get("noise_figure_db", 6)
            ),
            node_energy_mode={
                "environmental": "external",
                "always_powered": "external",
            }.get(mode, mode),
            node_ext_power_fn=lambda node: sources[node.id].ext_power,
            node_wpt_power_w=None if wpt_power is None else float(wpt_power),
            combine_mode=str(energy_config.get("combine_mode", "max")),
        )
        downlink = coverage.compute_bs_to_point(nodes)
        node_coverages = {}
        for node in nodes:
            device = self.scenario["devices"][names[node.id]]
            node_mode = str(device.get("energy_mode", mode)).lower()
            if node_mode not in {
                "wpt",
                "environmental",
                "external",
                "hybrid",
                "always_powered",
            }:
                raise ValueError(f"unsupported energy mode for {names[node.id]}")
            node_coverage = propagation.CoverageMap(
                base_stations=base_stations,
                nodes=[node],
                freq_hz=coverage.freq_hz,
                pathloss_model=coverage.pathloss_model,
                los=coverage.los,
                extra_np_per_m=coverage.extra_np_per_m,
                bandwidth_hz=coverage.bandwidth_hz,
                noise_figure_db=coverage.noise_figure_db,
                node_energy_mode={
                    "environmental": "external",
                    "always_powered": "external",
                }.get(node_mode, node_mode),
                node_ext_power_fn=lambda node: sources[node.id].ext_power,
                node_wpt_power_w=None if wpt_power is None else float(wpt_power),
                combine_mode=str(
                    device.get("combine_mode", energy_config.get("combine_mode", "max"))
                ),
            )
            node_coverage.calculate_node_power([node], downlink)
            node_coverages[node.id] = node_coverage
        uplink = coverage.compute_point_to_bs(nodes)
        cap_config = self.model.get("capacitor", {})
        ctl_config = self.model.get("controller", {})
        current_config = ctl_config.get("currents_a", self.model.get("currents_a", {}))
        timing_config = ctl_config.get(
            "durations_ms", self.model.get("durations_ms", {})
        )
        if "listening" in timing_config:
            warnings.warn(
                "durations_ms.listening is obsolete; periodic sensing and command slots determine listening time",
                stacklevel=2,
            )
        cap_params = capacitor.CapacitorParams(
            dt=float(cap_config.get("timestep_seconds", cap_config.get("dt", 0.001))),
            R_series=float(
                cap_config.get(
                    "series_resistance_ohm", cap_config.get("R_series", 5000)
                )
            ),
            R_leakage=float(
                cap_config.get(
                    "leakage_resistance_ohm", cap_config.get("R_leakage", 100000)
                )
            ),
            C=float(cap_config.get("capacitance_f", cap_config.get("C", 0.0003))),
        )
        ctl_params = controller.ControllerParams(
            currents=controller.CurrentsA(
                listening=float(current_config.get("listening", 0.00014)),
                sensing=float(current_config.get("sensing", 0.000512)),
                processing=float(current_config.get("processing", 0.00128)),
                transmitting=float(current_config.get("transmitting", 0.005)),
            ),
            durations_ms=controller.DurationsMs(
                listening=float(timing_config.get("listening", 5)),
                sensing=float(timing_config.get("sensing", 2)),
                processing=float(timing_config.get("processing", 5)),
                transmitting=float(timing_config.get("transmitting", 5)),
            ),
            thresholds_v=controller.VoltageThresholdsV(
                low=threshold(ctl_config, "threshold_low_v", "low_voltage_v", 1.3),
                high=threshold(ctl_config, "threshold_high_v", "high_voltage_v", 1.7),
            ),
            max_startup_time_ms=int(ctl_config.get("max_startup_time_ms", 2000)),
        )
        protocol_config = self.model.get("protocol", {"type": "broadcast"})
        protocol = resolve(
            str(protocol_config.get("type", "broadcast")),
            [node.id for node in nodes],
            protocol_config,
        )
        rx_durations = [
            entry[1] for entry in protocol.get("schedule", []) if entry[0] == "rx"
        ]
        if not rx_durations:
            rx_durations = [float(protocol_config.get("rx_duration_ms", 10))]
        if ctl_params.durations_ms.transmitting > min(rx_durations):
            raise ValueError("transmission airtime exceeds an advertised RX slot")
        capacitors = []
        modules = []
        controllers = []
        for node in nodes:
            device_config = self.scenario["devices"][names[node.id]]
            cap = capacitor.Capacitor(
                env=env,
                id=node.id,
                params=cap_params,
                initial_voltage=float(
                    device_config.get(
                        "initial_voltage_v", cap_config.get("initial_voltage_v", 0)
                    )
                ),
                voltage_max=float(cap_config.get("maximum_voltage_v", 2)),
                log_interval_s=float(cap_config.get("log_interval_seconds", 0.01)),
            )
            module = protocol["module_class"](env, node, [], uplink, downlink)
            module.rng = random.Random(f"{seed}:mac:{names[node.id]}")
            capacitors.append(cap)
            modules.append(module)
            interval = float(device_config.get("sensing_interval_ms", 1000))
            phase = device_config.get("sensing_phase_ms")
            if phase is None:
                phase = random.Random(f"{seed}:phase:{names[node.id]}").uniform(
                    0, interval
                )
            controllers.append(
                controller.Controller(
                    env,
                    cap,
                    node,
                    module,
                    ctl_params,
                    node_coverages[node.id],
                    downlink,
                    sensing_interval_ms=interval,
                    sensing_phase_ms=phase,
                    always_powered=str(device_config.get("energy_mode", mode)).lower()
                    == "always_powered",
                    rng=random.Random(f"{seed}:controller:{names[node.id]}"),
                    identity_prefix=f"{seed}:{names[node.id]}",
                )
            )
        receiver = self.model.get("receiver", {})
        if "collision_window_ms" in receiver:
            warnings.warn(
                "collision_window_ms is obsolete; decoding uses actual overlapping airtime",
                stacklevel=2,
            )
        behaviors = [
            bsengine.BSBehavior(
                env=env,
                base_station=base_station,
                schedule=protocol.get("schedule"),
                policy=protocol.get("policy"),
                backscatter_modules=modules,
                loop=True,
                enable_sic=bool(
                    receiver.get("sic", protocol_config.get("type") == "broadcast_sic")
                ),
                required_sinr_db=float(receiver.get("required_sinr_db", 3)),
                cancellation_factor=float(receiver.get("cancellation_factor", 0.9)),
                noise_figure_db=float(receiver.get("noise_figure_db", 6)),
                bandwidth_hz=float(receiver.get("bandwidth_hz", 100e6)),
            )
            for base_station in base_stations
        ]
        for behavior in behaviors:
            behavior.nodes_registered = [node.id for node in nodes]
        for module in modules:
            module.bs_processes = behaviors
            if bool(protocol_config.get("pre_registered", True)):
                module.state = "registered"
        env.run(until=duration_ms(self.model))
        for item in controllers:
            item.finalize_horizon()
        return {
            "environment": env,
            "nodes": nodes,
            "node_names": names,
            "base_station": base_stations[0],
            "base_stations": base_stations,
            "coverage": coverage,
            "node_coverages": node_coverages,
            "downlink": downlink,
            "uplink": uplink,
            "energy_source": sources[nodes[0].id],
            "energy_sources": sources,
            "capacitors": capacitors,
            "controllers": controllers,
            "backscatter_modules": modules,
            "bs_behavior": behaviors[0],
            "bs_behaviors": behaviors,
            "controller_transitions": sorted(
                (row for item in controllers for row in item.transitions),
                key=lambda row: (row["time_ms"], row["node_id"]),
            ),
        }

    def _nodes(self, seed: int):
        topology = self.model.get("topology", {})
        placement = topology.get("nodes", {}).get("placement", {})
        rng = random.Random(seed)
        names: dict[int, str] = {}
        nodes = []
        for node_id, (name, device) in enumerate(
            sorted(self.scenario["devices"].items())
        ):
            if "x" in device and "y" in device:
                x, y = float(device["x"]), float(device["y"])
            else:
                low = float(placement.get("min_radius_m", 10))
                high = float(placement.get("max_radius_m", 40))
                radius = rng.uniform(low, high)
                angle = rng.uniform(0, 2 * np.pi)
                x, y = radius * np.cos(angle), radius * np.sin(angle)
            names[node_id] = name
            nodes.append(
                radiodevices.Node(
                    id=node_id,
                    x=float(x),
                    y=float(y),
                    height=float(device.get("height_m", 1.5)),
                    node_type=str(device.get("node_type", "passive")),
                    radius=float(device.get("radius_m", 2)),
                    color=str(device.get("color", "")),
                    label=bool(device.get("label", True)),
                    sensitivity_dbm=float(device.get("sensitivity_dbm", -100)),
                    efficiency=float(device.get("efficiency", 0.7)),
                    antenna_type=str(device.get("antenna_type", "omni")),
                    antenna_gain_dbi=float(device.get("antenna_gain_dbi", 0)),
                    azimuth_deg=float(device.get("azimuth_deg", 0)),
                    beamwidth_deg=float(device.get("beamwidth_deg", 360)),
                    subcarrier_shift=int(device.get("subcarrier_shift", 0)),
                )
            )
        return nodes, names

    def _base_stations(self):
        topology = self.model.get("topology", {})
        configs = topology.get("base_stations") or [topology.get("base_station", {})]
        return [
            self._base_station(config, index) for index, config in enumerate(configs)
        ]

    @staticmethod
    def _base_station(config, default_id):
        sectors = config.get("sectors") or [
            {"azimuth_deg": 0, "beamwidth_deg": 65, "power_dbm": 46},
            {"azimuth_deg": 120, "beamwidth_deg": 65, "power_dbm": 46},
            {"azimuth_deg": 240, "beamwidth_deg": 65, "power_dbm": 46},
        ]
        return radiodevices.BaseStation(
            id=int(config.get("id", default_id)),
            x=float(config.get("x", 0)),
            y=float(config.get("y", 0)),
            site_radius=float(config.get("site_radius_m", 2)),
            sectors=[
                radiodevices.Sector(
                    azimuth_deg=float(item["azimuth_deg"]),
                    beamwidth_deg=float(item["beamwidth_deg"]),
                    power=float(item.get("power_dbm", 46)),
                    antenna_type=str(item.get("antenna_type", "3GPP")),
                    sensitivity_dbm=float(item.get("sensitivity_dbm", -100)),
                    height=float(item.get("height_m", config.get("height_m", 25))),
                    antenna_gain_dbi=float(item.get("antenna_gain_dbi", 15)),
                )
                for item in sectors
            ],
        )
