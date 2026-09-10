from __future__ import annotations
import copy, re
from pathlib import Path
import yaml

SUPPORTED_CORES = {"oai", "open5gs", "free5gc"}
SUPPORTED_RANS = {"oai", "srsran", "ueransim"}
SUPPORTED_PLATFORMS = {"rfsim", "r2lab", "physical"}


def load_scenario(path: str | Path) -> dict:
    source = Path(path).resolve()
    with source.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError("scenario must be a mapping")
    for section in ("deployment", "model", "mqtt", "devices"):
        if not isinstance(data.get(section), dict):
            raise ValueError(f"scenario requires mapping: {section}")
    dep = data["deployment"]
    if dep.get("core") not in SUPPORTED_CORES:
        raise ValueError("unsupported core")
    if str(dep.get("ran", "")).lower() not in SUPPORTED_RANS:
        raise ValueError("unsupported RAN")
    if dep.get("platform") not in SUPPORTED_PLATFORMS:
        raise ValueError("unsupported platform")
    ues = dep.get("ues", [])
    if (
        not isinstance(ues, list)
        or not ues
        or not all(
            isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name)
            for name in ues
        )
    ):
        raise ValueError("deployment.ues must be a non-empty list of names")
    if len(ues) != len(set(ues)):
        raise ValueError("deployment.ues must contain unique names")
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


def redacted(data: dict) -> dict:
    clean = copy.deepcopy(data)
    clean.pop("_source_directory", None)
    secret = re.compile(r"password|secret|token|credential|private_key", re.I)

    def walk(value):
        if isinstance(value, dict):
            return {
                k: ("<redacted>" if secret.search(str(k)) else walk(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(clean)
