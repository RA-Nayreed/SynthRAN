"""Series-source capacitor with leakage, constant-current load and energy accounting."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import simpy


@dataclass(frozen=True)
class CapacitorParams:
    dt: float = 1e-3
    R_series: float = 5e3
    R_leakage: float = 0.1e6
    C: float = 300e-6

    def __post_init__(self):
        if not all(
            math.isfinite(v) and v > 0 for v in (self.dt, self.R_series, self.C)
        ):
            raise ValueError(
                "capacitor timestep, series resistance and capacitance must be positive"
            )
        if math.isnan(self.R_leakage) or self.R_leakage <= 0:
            raise ValueError(
                "leakage resistance must be positive (infinity disables leakage)"
            )


@dataclass
class Capacitor:
    env: simpy.Environment
    id: int
    params: CapacitorParams = field(default_factory=CapacitorParams)
    keep_logs: bool = True
    initial_voltage: float = 0.0
    voltage_max: float = 2.0
    log_interval_s: float = 0.001
    voltage: float = field(init=False, default=0.0)
    internal_time: float = field(init=False, default=0.0)
    energy: float = field(init=False, default=0.0)
    voltage_source: float = field(init=False, default=0.0)
    current: float = field(init=False, default=0.0)
    voltage_history: list = field(init=False, default_factory=list)
    energy_account: dict = field(
        init=False,
        default_factory=lambda: {
            "source_j": 0.0,
            "series_loss_j": 0.0,
            "leakage_j": 0.0,
            "load_j": 0.0,
            "clamp_loss_j": 0.0,
        },
    )

    def __post_init__(self):
        if not math.isfinite(self.voltage_max) or self.voltage_max <= 0:
            raise ValueError("maximum capacitor voltage must be positive")
        if (
            not math.isfinite(self.initial_voltage)
            or not 0 <= self.initial_voltage <= self.voltage_max
        ):
            raise ValueError("initial capacitor voltage must lie within its limits")
        if not math.isfinite(self.log_interval_s) or self.log_interval_s <= 0:
            raise ValueError("voltage logging interval must be positive")
        self.voltage = self.initial_voltage
        self.energy = self.initial_energy = 0.5 * self.params.C * self.voltage**2
        self.R_series = self.params.R_series
        self._last_log_s = -math.inf
        self.action = self.env.process(self.run())

    @staticmethod
    def _trajectory(voltage, equilibrium, rate, seconds):
        difference = voltage - equilibrium
        decay = math.exp(-rate * seconds)
        integral_exp = -math.expm1(-rate * seconds) / rate
        integral_exp2 = -math.expm1(-2 * rate * seconds) / (2 * rate)
        integral_v = equilibrium * seconds + difference * integral_exp
        integral_v2 = (
            equilibrium**2 * seconds
            + 2 * equilibrium * difference * integral_exp
            + difference**2 * integral_exp2
        )
        return equilibrium + difference * decay, integral_v, max(0.0, integral_v2)

    def advance(self, load_current=0.0, *, seconds=None, source_enabled=True):
        """Integrate one held-input interval, including diode and voltage-limit crossings."""
        seconds = self.params.dt if seconds is None else float(seconds)
        if (
            not math.isfinite(seconds)
            or seconds <= 0
            or not math.isfinite(load_current)
            or load_current < 0
        ):
            raise ValueError(
                "integration interval must be positive and load current nonnegative"
            )
        if not math.isfinite(self.voltage_source) or self.voltage_source < 0:
            raise ValueError("source voltage must be finite and nonnegative")
        remaining = seconds
        p = self.params
        leakage_g = 1 / p.R_leakage
        while remaining > 1e-15:
            v = self.voltage
            source_g = (
                1 / p.R_series if source_enabled and v <= self.voltage_source else 0.0
            )
            conductance = source_g + leakage_g
            forcing = self.voltage_source * source_g - load_current
            derivative = (forcing - conductance * v) / p.C
            clamped = (v >= self.voltage_max and derivative >= 0) or (
                v <= 0 and derivative <= 0
            )
            interval = remaining
            if clamped:
                final, integral_v, integral_v2 = v, v * interval, v * v * interval
            elif conductance == 0:
                if derivative < 0:
                    interval = min(interval, -v / derivative)
                final = v + derivative * interval
                integral_v = v * interval + derivative * interval**2 / 2
                integral_v2 = (
                    v * v * interval
                    + v * derivative * interval**2
                    + derivative**2 * interval**3 / 3
                )
            else:
                rate = conductance / p.C
                equilibrium = forcing / conductance
                boundaries = [0.0, self.voltage_max]
                if source_enabled and source_g == 0:
                    boundaries.append(self.voltage_source)
                for boundary in boundaries:
                    if v == equilibrium or abs(boundary - v) < 1e-12:
                        continue
                    ratio = (boundary - equilibrium) / (v - equilibrium)
                    if 0 < ratio < 1:
                        interval = min(interval, -math.log(ratio) / rate)
                final, integral_v, integral_v2 = self._trajectory(
                    v, equilibrium, rate, interval
                )
            if interval <= 1e-15:
                raise ArithmeticError("capacitor boundary integration did not advance")
            source_j = (
                source_g
                * self.voltage_source
                * (self.voltage_source * interval - integral_v)
            )
            series_j = source_g * (
                self.voltage_source**2 * interval
                - 2 * self.voltage_source * integral_v
                + integral_v2
            )
            leak_j = leakage_g * integral_v2
            load_j = load_current * integral_v
            self.energy_account["source_j"] += source_j
            self.energy_account["series_loss_j"] += max(0.0, series_j)
            self.energy_account["leakage_j"] += max(0.0, leak_j)
            self.energy_account["load_j"] += max(0.0, load_j)
            if clamped:
                self.energy_account["clamp_loss_j"] += max(
                    0.0, source_j - series_j - leak_j - load_j
                )
            self.voltage = min(self.voltage_max, max(0.0, final))
            if abs(self.voltage - self.voltage_source) < 1e-12:
                self.voltage = self.voltage_source
            remaining -= interval
        self.internal_time += seconds
        self.energy = 0.5 * p.C * self.voltage**2
        if (
            self.keep_logs
            and self.internal_time - self._last_log_s >= self.log_interval_s - 1e-12
        ):
            self.voltage_history.append((self.internal_time, self.voltage))
            self._last_log_s = self.internal_time
        return self.voltage

    def capacitor_charging(self):
        return self.advance()

    def capacitor_selfdischarge(self):
        return self.advance(source_enabled=False)

    def load_discharging(self, current):
        return self.advance(current, source_enabled=False)

    def charge_and_discharge(self, load_current):
        return self.advance(load_current)

    def run(self):
        while True:
            try:
                yield self.env.timeout(10_000_000)
            except simpy.Interrupt as interrupt:
                handlers = {
                    "capacitor_charging": self.capacitor_charging,
                    "capacitor_full": self.capacitor_selfdischarge,
                    "capacitor_discharge": lambda: self.load_discharging(self.current),
                    "capacitor_charge_and_discharge": lambda: self.charge_and_discharge(
                        self.current
                    ),
                }
                handlers[interrupt.cause]()

    def charge_step(self, source_voltage):
        self.voltage_source = source_voltage
        return self.capacitor_charging()

    def discharge_step(self, load_current):
        self.current = load_current
        return self.load_discharging(load_current)

    def leak_step(self):
        return self.capacitor_selfdischarge()
