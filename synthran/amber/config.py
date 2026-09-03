"""Configuration adapters for Amber without modifying vendored source."""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


def duration_ms(model: dict[str, Any]) -> int:
    if "duration_ms" in model:
        return int(model["duration_ms"])
    return int(float(model.get("duration_seconds", 60)) * 1000)


def threshold(config: dict[str, Any], modern: str, legacy: str, default: float) -> float:
    return float(config.get(modern, config.get(legacy, default)))


class TraceEnergySource:
    """Expose CSV or built-in power traces through Amber's ext_power contract."""

    def __init__(self, env, config: dict[str, Any], source_directory: str | None = None):
        self.env = env
        self.config = config
        self.values = self._load(source_directory)
        self.ext_power = self.values[0]
        self.action = env.process(self.run())

    def _load(self, source_directory: str | None) -> list[float]:
        trace = str(self.config.get("trace", "builtin:stable"))
        units = str(self.config.get("units", "w")).lower()
        factor = {"w": 1.0, "mw": 1e-3, "uw": 1e-6}.get(units)
        if factor is None:
            raise ValueError(f"unsupported energy units: {units}")
        if trace.startswith("builtin:"):
            path = Path(__file__).parents[1] / "data" / f"{trace.split(':', 1)[1]}.csv"
        else:
            path = Path(trace)
            if not path.is_absolute() and source_directory:
                path = Path(source_directory) / path
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise ValueError(f"empty energy trace: {path}")
        column = self.config.get("column")
        if not column:
            column = next((key for key in rows[0] if key.lower() in {"power", "power_w", "watts", "value"}), None)
        if not column:
            numeric = [key for key in rows[0] if key.lower() not in {"time", "time_s", "timestamp"}]
            column = numeric[-1]
        return [max(0.0, float(row[column]) * factor) for row in rows]

    def run(self):
        repeat = bool(self.config.get("repeat", True))
        index = 0
        while True:
            self.ext_power = self.values[index]
            yield self.env.timeout(1)
            if index + 1 < len(self.values):
                index += 1
            elif repeat:
                index = 0


def watts_to_source_voltage(power_w: float, resistance_ohm: float) -> float:
    return math.sqrt(max(0.0, power_w) * resistance_ohm)
