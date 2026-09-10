"""Energy-gated periodic sensing and completed-airtime transmission."""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass

from .propagation import dbm_to_watts


@dataclass(frozen=True)
class CurrentsA:
    listening: float
    sensing: float
    processing: float
    transmitting: float


@dataclass(frozen=True)
class DurationsMs:
    listening: float
    sensing: float
    processing: float
    transmitting: float


@dataclass(frozen=True)
class VoltageThresholdsV:
    high: float
    low: float


@dataclass(frozen=True)
class ControllerParams:
    currents: CurrentsA
    durations_ms: DurationsMs
    thresholds_v: VoltageThresholdsV
    max_startup_time_ms: int = 2000


class Controller:
    """One pending sample, periodic opportunities, no retrospective catch-up."""

    def __init__(
        self,
        env,
        capacitor_ctrl,
        node,
        backscatter,
        params,
        coverage_map=None,
        downlink_results=None,
        keep_logs=True,
        *,
        sensing_interval_ms=1000.0,
        sensing_phase_ms=0.0,
        always_powered=False,
        rng=None,
        identity_prefix=None,
    ):
        self.env, self.id, self.node = env, node.id, node
        self.capacitor_ctrl, self.backscatter, self.p = (
            capacitor_ctrl,
            backscatter,
            params,
        )
        self.coverage_map, self.downlink_results = coverage_map, downlink_results
        self.keep_logs = keep_logs
        self.rng = rng or random.Random(node.id)
        self.identity_prefix = str(
            identity_prefix if identity_prefix is not None else node.id
        )
        self.interval_ms = float(sensing_interval_ms)
        self.next_opportunity_ms = float(sensing_phase_ms)
        if not math.isfinite(self.interval_ms) or self.interval_ms <= 0:
            raise ValueError("sensing_interval_ms must be finite and positive")
        if (
            not math.isfinite(self.next_opportunity_ms)
            or not 0 <= self.next_opportunity_ms < self.interval_ms
        ):
            raise ValueError("sensing_phase_ms must lie in [0, sensing_interval_ms)")
        if (
            not 0
            <= params.thresholds_v.low
            < params.thresholds_v.high
            <= capacitor_ctrl.voltage_max
        ):
            raise ValueError(
                "controller voltage thresholds must fit the capacitor limits"
            )
        if any(not math.isfinite(v) or v < 0 for v in vars(params.currents).values()):
            raise ValueError("controller currents must be finite and nonnegative")
        if any(
            not math.isfinite(v) or v <= 0 for v in vars(params.durations_ms).values()
        ):
            raise ValueError("controller durations must be finite and positive")
        self.always_powered = bool(always_powered)
        if (
            not math.isfinite(params.max_startup_time_ms)
            or params.max_startup_time_ms < 0
        ):
            raise ValueError("max_startup_time_ms must be finite and nonnegative")
        self.startup_ms = self.rng.uniform(0, params.max_startup_time_ms)
        self.state_name = "listening"
        self.is_active = False
        self.state_deadline_ms = math.inf
        self.pending_sample = None
        self.pending_tx_info = None
        self.current_opportunity = None
        self.opportunities = []
        self.events = []
        self.data_history = []
        self.sequence = 0
        self.processed_data = 0
        self.supplied_energy_j = 0.0
        self.transitions = []
        self._last_state = None
        if self.always_powered:
            capacitor_ctrl.voltage = capacitor_ctrl.voltage_max
            capacitor_ctrl.energy = capacitor_ctrl.initial_energy = (
                0.5 * capacitor_ctrl.params.C * capacitor_ctrl.voltage**2
            )
        if backscatter is not None:
            backscatter.controller = self
        self.action = env.process(self.run())

    @property
    def receive_enabled(self):
        return (
            self.is_active
            and self.env.now >= self.startup_ms
            and (
                self.always_powered
                or self.capacitor_ctrl.voltage > self.p.thresholds_v.low
            )
            and self.state_name in {"listening", "wait_slot"}
        )

    def _record(self, kind, **fields):
        row = {
            "time_ms": float(self.env.now),
            "node_id": self.id,
            "kind": kind,
            **fields,
        }
        self.events.append(row)
        return row

    def _power_state(self):
        cap = self.capacitor_ctrl
        if self.env.now < self.startup_ms:
            return
        if not self.is_active and (
            self.always_powered or cap.voltage >= self.p.thresholds_v.high
        ):
            self.is_active = True
        if (
            self.is_active
            and not self.always_powered
            and cap.voltage <= self.p.thresholds_v.low
        ):
            self.is_active = False
            if self.pending_tx_info is not None:
                self.backscatter.complete_transmission(False)
                self._record(
                    "transmission_energy_failure",
                    event_id=self.pending_tx_info.get("event_id"),
                )
            if (
                self.current_opportunity is not None
                and self.current_opportunity["outcome"] == "sensing_started"
            ):
                self.current_opportunity["outcome"] = "sensing_energy_failure"
            if self.pending_sample is not None:
                self._record(
                    "sample_lost_energy", event_id=self.pending_sample["event_id"]
                )
            self.pending_tx_info = self.pending_sample = None
            self.processed_data = 0
            self.state_name, self.state_deadline_ms = "listening", math.inf
            if self.backscatter is not None:
                self.backscatter.clear_slot()

    def _complete_state(self):
        if self.env.now + 1e-9 < self.state_deadline_ms or not self.is_active:
            return
        durations = self.p.durations_ms
        if self.state_name == "sensing":
            generated_ms = float(self.env.now)
            event_id = hashlib.sha256(
                f"{self.identity_prefix}:{self.sequence}:{generated_ms:.9f}".encode()
            ).hexdigest()[:20]
            self.pending_sample = {
                "event_id": event_id,
                "sequence": self.sequence,
                "generated_ms": generated_ms,
                "payload": self.rng.randint(100, 255),
            }
            self.sequence += 1
            self.current_opportunity["outcome"] = "generated"
            self.current_opportunity["event_id"] = event_id
            self._record("generated", **self.pending_sample)
            self.data_history.append(
                (generated_ms / 1000, self.pending_sample["payload"])
            )
            self.state_name = "processing"
            self.state_deadline_ms = self.env.now + durations.processing
        elif self.state_name == "processing":
            self.processed_data = self.pending_sample["payload"]
            self.state_name, self.state_deadline_ms = "wait_slot", math.inf
        elif self.state_name == "transmitting":
            self.backscatter.complete_transmission(True)
            self._record(
                "transmission_complete", event_id=self.pending_tx_info.get("event_id")
            )
            self.pending_tx_info = self.pending_sample = None
            self.processed_data = 0
            self.state_name, self.state_deadline_ms = "listening", math.inf

    def _sense_opportunity(self):
        if self.env.now + 1e-9 < self.next_opportunity_ms:
            return
        registered = self.backscatter is None or self.backscatter.state == "registered"
        if self.env.now < self.startup_ms:
            outcome = "startup_not_ready"
        elif not self.is_active:
            outcome = "energy_unavailable"
        elif not registered:
            outcome = "unregistered"
        elif self.state_name != "listening" or self.pending_sample is not None:
            outcome = "busy"
        else:
            outcome = "sensing_started"
            self.state_name = "sensing"
            self.state_deadline_ms = self.env.now + self.p.durations_ms.sensing
        row = {
            "time_ms": self.next_opportunity_ms,
            "node_id": self.id,
            "opportunity_index": len(self.opportunities),
            "outcome": outcome,
        }
        self.opportunities.append(row)
        if outcome == "sensing_started":
            self.current_opportunity = row
        self.next_opportunity_ms += self.interval_ms

    def _start_transmission(self):
        if (
            not self.is_active
            or self.backscatter is None
            or self.state_name not in {"listening", "wait_slot"}
        ):
            return
        if self.backscatter.state == "registered" and self.pending_sample is None:
            return
        info = self.backscatter.controller_tx_ready(
            self.processed_data, self.p.durations_ms.transmitting
        )
        if info is None:
            return
        if self.pending_sample is not None:
            info.update(self.pending_sample)
        info.update(
            start_ms=float(self.env.now),
            end_ms=float(self.env.now + self.p.durations_ms.transmitting),
            energy_complete=False,
        )
        self.pending_tx_info = info
        self.state_name = "transmitting"
        self.state_deadline_ms = info["end_ms"]
        self._record("transmission_start", event_id=info.get("event_id"))
        self.backscatter.do_transmit(info)

    def _step_duration(self):
        now = float(self.env.now)
        targets = [
            now + self.capacitor_ctrl.params.dt * 1000,
            self.next_opportunity_ms,
            self.state_deadline_ms,
        ]
        if self.startup_ms > now:
            targets.append(self.startup_ms)
        if self.backscatter is not None and self.backscatter.chosen_slot_idx >= 0:
            slot = self.backscatter.rx_slots[self.backscatter.chosen_slot_idx]
            if slot[0] > now:
                targets.append(slot[0])
        return min(target for target in targets if target > now + 1e-9) - now

    def run(self):
        while True:
            self._power_state()
            self._complete_state()
            self._sense_opportunity()
            self._start_transmission()
            self.node.state = self.state_name
            state = (self.state_name, self.is_active)
            if self._last_state != state:
                self.transitions.append(
                    {
                        "time_ms": float(self.env.now),
                        "node_id": self.id,
                        "state": self.state_name,
                        "active": self.is_active,
                        "voltage_v": self.capacitor_ctrl.voltage,
                    }
                )
                self._last_state = state
            current = (
                0.0
                if not self.is_active
                else getattr(
                    self.p.currents,
                    self.state_name if self.state_name != "wait_slot" else "listening",
                )
            )
            self._held_current = current
            if self.coverage_map is not None:
                self.coverage_map.calculate_node_power(
                    [self.node], self.downlink_results
                )
            cap = self.capacitor_ctrl
            cap.voltage_source = math.sqrt(
                dbm_to_watts(self.node.harvesting_power_dbm) * cap.params.R_series
            )
            interval_ms = self._step_duration()
            yield self.env.timeout(interval_ms)
            self._advance_power(current, interval_ms / 1000)

    def _advance_power(self, current, seconds):
        cap = self.capacitor_ctrl
        if self.always_powered:
            self.supplied_energy_j += (
                cap.voltage * current + cap.voltage**2 / cap.params.R_leakage
            ) * seconds
            cap.internal_time += seconds
            if (
                cap.keep_logs
                and cap.internal_time - cap._last_log_s >= cap.log_interval_s - 1e-12
            ):
                cap.voltage_history.append((cap.internal_time, cap.voltage))
                cap._last_log_s = cap.internal_time
        else:
            cap.advance(current, seconds=seconds)

    def finalize_horizon(self):
        seconds = self.env.now / 1000 - self.capacitor_ctrl.internal_time
        if seconds > 1e-12:
            self._advance_power(self._held_current, seconds)
