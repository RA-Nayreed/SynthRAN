# Copyright 2026 Rezwan Ahmad Nayreed
# SPDX-License-Identifier: Apache-2.0

"""Validated, timestamp-aware harvesting inputs."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np


def duration_ms(model):
    value = float(
        model.get("duration_ms", float(model.get("duration_seconds", 60)) * 1000)
    )
    if not math.isfinite(value) or value <= 0:
        raise ValueError("model duration must be finite and positive")
    return value


def threshold(config, modern, legacy, default):
    return float(config.get(modern, config.get(legacy, default)))


class TraceEnergySource:
    """Power in watts evaluated on the trace's seconds time axis."""

    def __init__(self, env, config, source_directory=None, *, series=None):
        self.env = env
        self.config = dict(config)
        self.times_s, self.values = (
            series if series is not None else self._load(source_directory)
        )
        self.times_s = np.asarray(self.times_s, dtype=float)
        self.values = np.asarray(self.values, dtype=float)
        if (
            not len(self.values)
            or len(self.times_s) != len(self.values)
            or not np.isfinite(self.values).all()
            or (self.values < 0).any()
            or not np.isfinite(self.times_s).all()
            or self.times_s[0] != 0
            or (np.diff(self.times_s) <= 0).any()
        ):
            raise ValueError(
                "energy samples require finite nonnegative power and increasing times starting at zero"
            )
        self.interpolation = str(config.get("interpolation", "hold")).lower()
        if self.interpolation not in {"hold", "linear"}:
            raise ValueError("energy interpolation must be hold or linear")
        self.repeat = bool(config.get("repeat", True))
        last_interval = (
            self.times_s[-1] - self.times_s[-2] if len(self.times_s) > 1 else 1.0
        )
        self.period_s = float(config.get("period_s", self.times_s[-1] + last_interval))
        if (
            not math.isfinite(self.period_s)
            or self.period_s <= 0
            or self.period_s < self.times_s[-1]
        ):
            raise ValueError("energy period_s must cover the trace")

    def _load(self, source_directory):
        if "constant_power_w" in self.config:
            return [0.0], [float(self.config["constant_power_w"])]
        trace = str(self.config.get("trace", "builtin:stable"))
        path = (
            Path(__file__).parents[1] / "data" / f"{trace.split(':', 1)[1]}.csv"
            if trace.startswith("builtin:")
            else Path(trace)
        )
        if not path.is_absolute() and source_directory:
            path = Path(source_directory) / path
        if path.suffix.lower() in {".xlsx", ".xls"}:
            import pandas as pd

            rows = pd.read_excel(path).to_dict("records")
        else:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
        if not rows:
            raise ValueError(f"empty energy trace: {path}")
        time_column = self.config.get("time_column") or next(
            (
                key
                for key in ("time_s", "time_ms", "time", "timestamp")
                if key in rows[0]
            ),
            None,
        )
        if time_column is None:
            raise ValueError("energy trace requires an explicit time column")
        time_factor = 0.001 if time_column == "time_ms" else 1.0
        column = self.config.get("column") or next(
            (
                key
                for key in rows[0]
                if key.lower().startswith(("power", "voltage"))
                or key.lower() in {"watts", "value"}
            ),
            None,
        )
        if column is None:
            raise ValueError("energy trace requires a power/voltage column")
        voltage = str(self.config.get("trace_kind", "power")).lower() == "voltage"
        inferred = column.rsplit("_", 1)[-1].lower()
        default_units = (
            inferred
            if inferred in {"w", "mw", "uw", "v", "mv"}
            else ("v" if voltage else "w")
        )
        units = str(self.config.get("units", default_units)).lower()
        factors = (
            {"v": 1.0, "mv": 1e-3} if voltage else {"w": 1.0, "mw": 1e-3, "uw": 1e-6}
        )
        if units not in factors:
            raise ValueError(f"unsupported energy units: {units}")
        values = [float(row[column]) * factors[units] for row in rows]
        if voltage:
            resistance = float(self.config.get("resistance_ohm", 5000))
            if not math.isfinite(resistance) or resistance <= 0 or min(values) < 0:
                raise ValueError(
                    "voltage traces require nonnegative voltages and positive resistance"
                )
            values = [value * value / resistance for value in values]
        return [float(row[time_column]) * time_factor for row in rows], values

    def power_at(self, time_s):
        time_s = max(0.0, float(time_s))
        if self.repeat:
            time_s %= self.period_s
        if self.interpolation == "linear":
            return float(np.interp(time_s, self.times_s, self.values))
        index = min(
            len(self.values) - 1,
            int(np.searchsorted(self.times_s, time_s, side="right")) - 1,
        )
        return float(self.values[index])

    @property
    def ext_power(self):
        return self.power_at(self.env.now / 1000.0)


def _ou_series(rng, count, step_s, tau_s):
    coefficient = math.exp(-step_s / tau_s)
    values = np.empty(count)
    values[0] = rng.normal()
    innovations = rng.normal(size=count - 1)
    scale = math.sqrt(1 - coefficient * coefficient)
    for index, innovation in enumerate(innovations, 1):
        values[index] = coefficient * values[index - 1] + scale * innovation
    return values


def energy_sources(
    env, config, devices, names, model_duration_ms, seed, source_directory
):
    """Separate exogenous streams from MAC/controller RNG consumption."""
    dependence = config.get("correlation", "common")
    correlation = float({"common": 1.0, "independent": 0.0}.get(dependence, dependence))
    if not 0 <= correlation <= 1:
        raise ValueError(
            "energy correlation must be common, independent or a number in [0, 1]"
        )
    if config.get("source", "trace") not in {"trace", "lognormal"}:
        raise ValueError("energy source must be trace or lognormal")
    stochastic = config.get("source") == "lognormal"
    if stochastic:
        mean = float(config["mean_power_w"])
        cv = float(config.get("coefficient_of_variation", 1.0))
        step = float(config.get("sample_interval_s", 0.1))
        tau = float(config.get("correlation_time_s", 5.0))
        if (
            not all(math.isfinite(v) and v > 0 for v in (mean, step, tau))
            or not math.isfinite(cv)
            or cv < 0
        ):
            raise ValueError("invalid lognormal energy parameters")
        times = np.arange(math.ceil(model_duration_ms / 1000 / step) + 1) * step
        common = _ou_series(np.random.default_rng([seed, 710]), len(times), step, tau)
        sigma = math.sqrt(math.log1p(cv * cv))
    sources = {}
    for node_id, name in names.items():
        override = devices[name].get("energy", {})
        effective = {**config, **override}
        if stochastic and not override:
            independent = _ou_series(
                np.random.default_rng([seed, 711, node_id]), len(times), step, tau
            )
            latent = (
                math.sqrt(correlation) * common
                + math.sqrt(1 - correlation) * independent
            )
            powers = mean * np.exp(sigma * latent - sigma * sigma / 2)
            sources[node_id] = TraceEnergySource(
                env, {**effective, "repeat": False}, series=(times, powers)
            )
        else:
            if stochastic and not ({"trace", "constant_power_w"} & override.keys()):
                raise ValueError(
                    "a per-sensor override of a lognormal source requires an explicit trace or constant power"
                )
            if not stochastic and correlation != 1 and "trace" not in override:
                raise ValueError(
                    "independent CSV inputs require devices.<sensor>.energy.trace for every sensor"
                )
            sources[node_id] = TraceEnergySource(env, effective, source_directory)
    return sources


def watts_to_source_voltage(power_w, resistance_ohm):
    return math.sqrt(max(0.0, power_w) * resistance_ohm)
