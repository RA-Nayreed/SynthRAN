"""Build and execute a complete embedded-Amber experiment."""
from __future__ import annotations

import random
from typing import Any

import numpy as np
import simpy
from amber import backscatter, bsengine, capacitor, controller, propagation, radiodevices

from .config import TraceEnergySource, duration_ms, threshold
from .protocols import resolve


class ConfiguredBSBehavior(bsengine.BSBehavior):
    """Keep Amber's receiver authoritative while exposing its collision window."""

    def __init__(self, *args, collision_window_ms: float = 5.0, **kwargs):
        self.collision_window_ms = collision_window_ms
        super().__init__(*args, **kwargs)

    def _process_rx_buffer(self, collision_window_ms: float | None = None):
        return super()._process_rx_buffer(
            self.collision_window_ms if collision_window_ms is None else collision_window_ms
        )


class AmberRunner:
    """Turn a SynthRAN scenario into native Amber simulation objects."""

    def __init__(self, scenario: dict[str, Any]):
        self.scenario = scenario
        self.model = scenario["model"]
        if str(self.model.get("engine", "amber")).lower() != "amber":
            raise ValueError("model.engine must be amber")

    def run(self) -> dict[str, Any]:
        seed = int(self.model.get("seed", 1))
        random.seed(seed)
        np.random.seed(seed)
        env = simpy.Environment()
        nodes, names = self._nodes(seed)
        base_station = self._base_station()
        energy_config = self.model.get("energy", {})
        source = TraceEnergySource(env, energy_config, self.scenario.get("_source_directory"))
        mode = str(energy_config.get("mode", "hybrid")).lower()
        coverage = propagation.CoverageMap(
            base_stations=[base_station],
            nodes=nodes,
            freq_hz=float(self.model.get("propagation", self.model.get("topology", {})).get("frequency_hz", 924e6)),
            pathloss_model=str(self.model.get("propagation", {}).get("model", self.model.get("topology", {}).get("pathloss", "macro"))),
            los=bool(self.model.get("propagation", {}).get("los", True)),
            extra_np_per_m=float(self.model.get("propagation", {}).get("extra_np_per_m", 0)),
            bandwidth_hz=float(self.model.get("receiver", {}).get("bandwidth_hz", 100e6)),
            noise_figure_db=float(self.model.get("receiver", {}).get("noise_figure_db", 6)),
            node_energy_mode={"environmental": "external"}.get(mode, mode),
            node_ext_power_fn=lambda _node: source.ext_power,
            combine_mode=str(energy_config.get("combine_mode", "max")),
        )
        downlink = coverage.compute_bs_to_point(nodes)
        coverage.calculate_node_power(nodes, downlink)
        uplink = coverage.compute_point_to_bs(nodes)
        cap_config = self.model.get("capacitor", {})
        ctl_config = self.model.get("controller", {})
        current_config = ctl_config.get("currents_a", self.model.get("currents_a", {}))
        timing_config = ctl_config.get("durations_ms", self.model.get("durations_ms", {}))
        cap_params = capacitor.CapacitorParams(
            dt=float(cap_config.get("timestep_seconds", cap_config.get("dt", 0.001))),
            R_series=float(cap_config.get("series_resistance_ohm", cap_config.get("R_series", 5000))),
            R_leakage=float(cap_config.get("leakage_resistance_ohm", cap_config.get("R_leakage", 100000))),
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
                listening=int(timing_config.get("listening", 5)),
                sensing=int(timing_config.get("sensing", 2)),
                processing=int(timing_config.get("processing", 5)),
                transmitting=int(timing_config.get("transmitting", 15)),
            ),
            thresholds_v=controller.VoltageThresholdsV(
                low=threshold(ctl_config, "threshold_low_v", "low_voltage_v", 1.3),
                high=threshold(ctl_config, "threshold_high_v", "high_voltage_v", 1.7),
            ),
            max_startup_time_ms=int(ctl_config.get("max_startup_time_ms", 2000)),
        )
        protocol_config = self.model.get("protocol", {"type": "broadcast"})
        protocol = resolve(str(protocol_config.get("type", "broadcast")), [node.id for node in nodes], protocol_config)
        capacitors = []
        modules = []
        controllers = []
        for node in nodes:
            device_config = self.scenario["devices"][names[node.id]]
            cap = capacitor.Capacitor(
                env=env,
                id=node.id,
                params=cap_params,
                initial_voltage=float(device_config.get("initial_voltage_v", cap_config.get("initial_voltage_v", 0))),
                voltage_max=float(cap_config.get("maximum_voltage_v", 2)),
            )
            # Amber Controller supports this public compatibility attribute and
            # otherwise falls back to 5 kohm; make scenario control explicit.
            cap.R_series = cap_params.R_series
            module = protocol["module_class"](env, node, [], uplink, downlink)
            capacitors.append(cap)
            modules.append(module)
            controllers.append(controller.Controller(env, cap, node, module, ctl_params, coverage, downlink))
        receiver = self.model.get("receiver", {})
        behavior = ConfiguredBSBehavior(
            env=env,
            base_station=base_station,
            schedule=protocol.get("schedule"),
            policy=protocol.get("policy"),
            backscatter_modules=modules,
            loop=True,
            enable_sic=bool(receiver.get("sic", protocol_config.get("type") == "broadcast_sic")),
            required_sinr_db=float(receiver.get("required_sinr_db", 3)),
            cancellation_factor=float(receiver.get("cancellation_factor", 0.9)),
            noise_figure_db=float(receiver.get("noise_figure_db", 6)),
            bandwidth_hz=float(receiver.get("bandwidth_hz", 100e6)),
            collision_window_ms=float(receiver.get("collision_window_ms", 5)),
        )
        behavior.nodes_registered = [node.id for node in nodes]
        for module in modules:
            module.bs_processes = [behavior]
            module.state = "registered"
        env.run(until=duration_ms(self.model))
        return {
            "environment": env,
            "nodes": nodes,
            "node_names": names,
            "base_station": base_station,
            "coverage": coverage,
            "downlink": downlink,
            "uplink": uplink,
            "energy_source": source,
            "capacitors": capacitors,
            "controllers": controllers,
            "backscatter_modules": modules,
            "bs_behavior": behavior,
        }

    def _nodes(self, seed: int):
        topology = self.model.get("topology", {})
        placement = topology.get("nodes", {}).get("placement", {})
        rng = random.Random(seed)
        names: dict[int, str] = {}
        nodes = []
        for node_id, (name, device) in enumerate(sorted(self.scenario["devices"].items())):
            if "x" in device and "y" in device:
                x, y = float(device["x"]), float(device["y"])
            else:
                low = float(placement.get("min_radius_m", 5))
                high = float(placement.get("max_radius_m", 40))
                radius = rng.uniform(low, high)
                angle = rng.uniform(0, 2 * np.pi)
                x, y = radius * np.cos(angle), radius * np.sin(angle)
            names[node_id] = name
            nodes.append(radiodevices.Node(
                id=node_id, x=float(x), y=float(y), height=float(device.get("height_m", 1.5)),
                sensitivity_dbm=float(device.get("sensitivity_dbm", -100)),
                efficiency=float(device.get("efficiency", 0.7)),
                antenna_type=str(device.get("antenna_type", "omni")),
                antenna_gain_dbi=float(device.get("antenna_gain_dbi", 0)),
                subcarrier_shift=int(device.get("subcarrier_shift", node_id)),
            ))
        return nodes, names

    def _base_station(self):
        config = self.model.get("topology", {}).get("base_station", {})
        sectors = config.get("sectors") or [
            {"azimuth_deg": 0, "beamwidth_deg": 65, "power_dbm": 46},
            {"azimuth_deg": 120, "beamwidth_deg": 65, "power_dbm": 46},
            {"azimuth_deg": 240, "beamwidth_deg": 65, "power_dbm": 46},
        ]
        return radiodevices.BaseStation(
            id=int(config.get("id", 0)), x=float(config.get("x", 0)), y=float(config.get("y", 0)),
            site_radius=float(config.get("site_radius_m", 2)),
            sectors=[radiodevices.Sector(
                azimuth_deg=float(item["azimuth_deg"]), beamwidth_deg=float(item["beamwidth_deg"]),
                power=float(item.get("power_dbm", 46)), antenna_type=str(item.get("antenna_type", "3GPP")),
                sensitivity_dbm=float(item.get("sensitivity_dbm", -100)), height=float(item.get("height_m", config.get("height_m", 25))),
                antenna_gain_dbi=float(item.get("antenna_gain_dbi", 15)),
            ) for item in sectors],
        )
