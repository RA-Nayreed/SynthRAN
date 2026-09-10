"""Ambient-IoT experiment configuration and logical sensor mappings."""
from __future__ import annotations

import re
import yaml
from pathlib import Path

from synthran.scenario import load_scenario as load_testbed, redacted


def load_scenario(path: str | Path) -> dict:
    source = Path(path).resolve()
    raw = yaml.safe_load(source.read_text())
    data = load_testbed(source) if isinstance(raw, dict) and 'deployment' in raw else raw
    if not isinstance(data, dict):
        raise ValueError('experiment scenario must be a mapping')
    experiment_config = data.get('experiment', {}).get('config')
    if experiment_config:
        source = Path(experiment_config)
        settings = yaml.safe_load(source.read_text())
        for key in ('model', 'mqtt', 'devices'):
            data[key] = settings[key]
    for section in ('model', 'mqtt', 'devices'):
        if not isinstance(data.get(section), dict):
            raise ValueError(f'experiment requires mapping: {section}')
    ues = data.get('deployment', {}).get('ues', data.get('gateways', []))
    if not data["devices"]:
        raise ValueError("devices must define at least one sensor")
    for name, device in data["devices"].items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name)
            or not isinstance(device, dict)
        ):
            raise ValueError("devices must map safe sensor names to configurations")
        gateway = device.get("gateway", name if name in ues else None)
        if gateway not in ues:
            raise ValueError(f"sensor {name!r} requires a gateway from deployment.ues")
        device["gateway"] = gateway
    data["_source_directory"] = str(source.parent)
    trace = data["model"].get("energy", {}).get("trace")
    if trace and not str(trace).startswith("builtin:"):
        data["model"]["energy"]["trace"] = str((source.parent / trace).resolve())
    for device in data["devices"].values():
        trace = device.get("energy", {}).get("trace")
        if trace and not str(trace).startswith("builtin:"):
            device["energy"]["trace"] = str((source.parent / trace).resolve())
    return data


def remap_gateways(scenario: dict, selected: list[str]) -> None:
    if not selected:
        raise ValueError("at least one gateway UE is required")
    original = list(scenario["deployment"]["ues"])
    replacement = {
        gateway: selected[index % len(selected)]
        for index, gateway in enumerate(original)
    }
    for name, device in scenario["devices"].items():
        gateway = device.get("gateway", name if name in original else None)
        target = gateway if gateway in selected else replacement.get(gateway)
        if target is None:
            raise ValueError(f"sensor {name!r} references unknown gateway {gateway!r}")
        device["gateway"] = target
    scenario["deployment"]["ues"] = list(selected)
