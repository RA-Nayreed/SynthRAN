from __future__ import annotations
import copy, re
from pathlib import Path
import yaml

SUPPORTED_CORES = {"oai", "open5gs", "free5gc"}
SUPPORTED_RANS = {"oai", "srsran", "ueransim"}
SUPPORTED_PLATFORMS = {"rfsim", "r2lab", "physical"}

def load_scenario(path: str | Path) -> dict:
    source = Path(path).resolve()
    with source.open(encoding="utf-8") as stream: data = yaml.safe_load(stream)
    for section in ("deployment", "model", "mqtt", "devices"):
        if not isinstance(data.get(section), dict): raise ValueError(f"scenario requires mapping: {section}")
    dep = data["deployment"]
    if dep.get("core") not in SUPPORTED_CORES: raise ValueError("unsupported core")
    if str(dep.get("ran", "")).lower() not in SUPPORTED_RANS: raise ValueError("unsupported RAN")
    if dep.get("platform") not in SUPPORTED_PLATFORMS: raise ValueError("unsupported platform")
    if set(dep.get("ues", [])) != set(data["devices"]): raise ValueError("deployment.ues must match devices")
    data["_source_directory"] = str(source.parent)
    trace = data["model"].get("energy", {}).get("trace")
    if trace and not str(trace).startswith("builtin:"): data["model"]["energy"]["trace"] = str((source.parent / trace).resolve())
    return data

def redacted(data: dict) -> dict:
    clean = copy.deepcopy(data); clean.pop("_source_directory", None)
    secret = re.compile(r"password|secret|token|credential|private_key", re.I)
    def walk(value):
        if isinstance(value, dict): return {k: ("<redacted>" if secret.search(str(k)) else walk(v)) for k, v in value.items()}
        if isinstance(value, list): return [walk(v) for v in value]
        return value
    return walk(clean)
