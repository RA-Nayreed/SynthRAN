"""Deterministic energy gate used to freeze real-network workloads."""
from __future__ import annotations
import hashlib, json, math, random
from dataclasses import dataclass
from typing import Callable
from .energy import EnergyTrace

@dataclass
class DeviceState:
    name: str
    voltage_v: float
    state: str = "sleep"
    harvested_j: float = 0.0
    consumed_j: float = 0.0

class EnergyWorkloadModel:
    """Advance capacitors and emit only energetically feasible MQTT events."""
    def __init__(self, scenario: dict, harvester_hook: Callable | None = None, scheduler_hook: Callable | None = None):
        self.scenario, self.model = scenario, scenario["model"]
        self.trace = EnergyTrace.from_config(self.model.get("energy", {}))
        self.random = random.Random(int(self.model.get("seed", 1)))
        self.harvester_hook, self.scheduler_hook = harvester_hook, scheduler_hook

    def run(self) -> dict:
        duration = float(self.model["duration_seconds"]); cap = self.model.get("capacitor", {}); ctl = self.model.get("controller", {})
        dt = float(cap.get("timestep_seconds", .001)); capacitance = float(cap.get("capacitance_f", .0003)); leakage = float(cap.get("leakage_resistance_ohm", 100000)); vmax = float(cap.get("maximum_voltage_v", 2)); high = float(ctl.get("high_voltage_v", 1.7)); low = float(ctl.get("low_voltage_v", 1.3))
        events, suppressed, histories, transitions, states, candidates = [], [], {}, [], {}, {}
        for name, cfg in sorted(self.scenario["devices"].items()):
            states[name] = DeviceState(name, float(cfg.get("initial_voltage_v", cap.get("initial_voltage_v", 0))))
            interval = float(cfg.get("sensing_interval_ms", 1000)) / 1000
            candidates[name] = {round(x * interval, 9) for x in range(1, int(duration / interval) + 1)}; histories[name] = []
        for step in range(int(math.ceil(duration / dt)) + 1):
            now = min(round(step * dt, 9), duration)
            for name, cfg in sorted(self.scenario["devices"].items()):
                state = states[name]; mode = cfg.get("energy_mode", self.model.get("energy", {}).get("mode", "environmental"))
                env_w = self.trace.watts_at(now) if mode in {"environmental", "external", "hybrid"} else 0.; wpt_w = float(cfg.get("wpt_power_w", self.model.get("energy", {}).get("wpt_power_w", 25e-6))) if mode in {"wpt", "hybrid"} else 0.
                harvested_w = self.harvester_hook(name, now, env_w, wpt_w) if self.harvester_hook else env_w + wpt_w
                leaked = state.voltage_v * math.exp(-dt / (leakage * capacitance)); energy = .5 * capacitance * leaked**2 + harvested_w * dt
                state.harvested_j += harvested_w * dt; state.voltage_v = min(vmax, math.sqrt(max(0., 2 * energy / capacitance)))
                old = state.state
                if state.state == "sleep" and state.voltage_v >= high: state.state = "ready"
                elif state.state == "ready" and state.voltage_v < low: state.state = "sleep"
                if old != state.state: transitions.append({"time_s": now, "device": name, "from": old, "to": state.state, "voltage_v": state.voltage_v})
                if now in candidates[name]:
                    currents = cfg.get("currents_a", self.model.get("currents_a", {"sensing": .0005, "processing": .0008, "transmitting": .002})); durations = cfg.get("durations_ms", self.model.get("durations_ms", {"sensing": 2, "processing": 2, "transmitting": 4}))
                    required = sum(state.voltage_v * float(currents[k]) * float(durations[k]) / 1000 for k in ("sensing", "processing", "transmitting")); available = .5 * capacitance * max(0., state.voltage_v**2 - low**2); allowed = state.state == "ready" and available >= required
                    if self.scheduler_hook: allowed = bool(self.scheduler_hook(name, now, allowed))
                    record = {"time_offset_s": now, "device": name, "voltage_v": state.voltage_v, "required_energy_j": required, "available_energy_j": available}
                    if allowed:
                        sequence = sum(e["device"] == name for e in events); event_id = hashlib.sha256(f"{name}:{now}:{sequence}".encode()).hexdigest()[:20]; payload = {"event_id": event_id, "device": name, "sequence": sequence, "modeled_time_s": now, "value": self.random.randint(100, 255)}
                        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")); requested_bytes = int(self.scenario["mqtt"].get("payload_bytes", 0))
                        if requested_bytes > len(encoded.encode("utf-8")) + 13:
                            payload["padding"] = "x" * (requested_bytes - len(encoded.encode("utf-8")) - 13); encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                        record.update({"topic": f'{self.scenario["mqtt"].get("topic_prefix", "synthran")}/{name}', "payload": encoded, "event_id": event_id}); events.append(record); state.consumed_j += required; state.voltage_v = math.sqrt(max(0., state.voltage_v**2 - 2 * required / capacitance))
                    else: record["reason"] = "controller_sleeping" if state.state != "ready" else "insufficient_energy"; suppressed.append(record)
                histories[name].append({"time_s": now, "voltage_v": state.voltage_v, "harvested_energy_j": state.harvested_j, "consumed_energy_j": state.consumed_j, "controller_state": state.state})
        return {"events": events, "suppressed": suppressed, "histories": histories, "transitions": transitions}
