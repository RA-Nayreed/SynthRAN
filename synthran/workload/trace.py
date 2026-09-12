from __future__ import annotations
import json
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import yaml
from synthran.ambient_iot import AmbientIoTRunner
from synthran.ambient_iot.evidence import write as write_ambient_iot_evidence
from synthran.experiment_scenario import load_scenario
from synthran.scenario import redacted
from .bundle import digest, write_manifest


def implementation_fingerprint():
    root = Path(__file__).parents[1]
    packages = {}
    for name in ("numpy", "simpy", "PyYAML", "pandas", "paho-mqtt"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {
        "python": platform.python_version(),
        "packages": packages,
        "source_sha256": {
            str(path.relative_to(root)): digest(path)
            for path in sorted(root.rglob("*.py"))
        },
    }


def generate(config: str | Path, output: str | Path) -> Path:
    scenario = load_scenario(config)
    destination = Path(output)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("refusing to overwrite an existing model run")
    destination.mkdir(parents=True, exist_ok=True)
    result = AmbientIoTRunner(scenario).run()
    (destination / "resolved-scenario.yml").write_text(
        yaml.safe_dump(redacted(scenario), sort_keys=False), encoding="utf-8"
    )
    bridge = write_ambient_iot_evidence(result, scenario, destination)
    with (destination / "events.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        for row in bridge["events"]:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    with (destination / "suppressed.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        for row in bridge["suppressed"]:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    write_manifest(
        destination,
        {
            "duration_seconds": result["environment"].now / 1000,
            "event_count": len(bridge["events"]),
            "seed": scenario["model"].get("seed", 1),
            "sensor_gateways": {
                name: device["gateway"] for name, device in scenario["devices"].items()
            },
            "mqtt": redacted(scenario["mqtt"]),
            "transformation": {"variant": "native", "generation_age_valid": True},
            "implementation": implementation_fingerprint(),
            "model_contract": "periodic-sensing-completed-airtime-v1",
        },
    )
    return destination / "events.jsonl"
