"""Deterministic environmental energy traces (CSV only)."""
from __future__ import annotations
import csv
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

_UNIT_SCALE = {"w": 1.0, "mw": 1e-3, "uw": 1e-6, "µw": 1e-6, "nw": 1e-9}

@dataclass(frozen=True)
class EnergyTrace:
    samples: tuple[tuple[float, float], ...]
    repeat: bool = True
    interpolation: str = "previous"

    @classmethod
    def from_config(cls, config: dict) -> "EnergyTrace":
        source = config.get("trace", "builtin:stable")
        path = files("synthran.data").joinpath("stable.csv") if source == "builtin:stable" else Path(source)
        time_col, value_col = config.get("time_column", "time_s"), config.get("value_column", "power_uw")
        scale = _UNIT_SCALE[config.get("units", "uw").lower()]
        with path.open("r", encoding="utf-8", newline="") as stream:
            rows = tuple((float(r[time_col]), float(r[value_col]) * scale) for r in csv.DictReader(stream))
        if not rows: raise ValueError(f"energy trace is empty: {path}")
        return cls(rows, bool(config.get("repeat", True)), config.get("interpolation", "previous"))

    @property
    def period(self) -> float:
        return self.samples[-1][0] if len(self.samples) > 1 else 1.0

    def watts_at(self, time_s: float) -> float:
        if self.repeat and self.period > 0: time_s %= self.period
        if time_s <= self.samples[0][0]: return self.samples[0][1]
        for i in range(1, len(self.samples)):
            t1, v1 = self.samples[i]
            if time_s <= t1:
                t0, v0 = self.samples[i - 1]
                return v0 + (v1 - v0) * ((time_s - t0) / (t1 - t0)) if self.interpolation == "linear" and t1 != t0 else v0
        return self.samples[-1][1]
