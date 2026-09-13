"""Prepared-workload and accepted-testbed runtime helpers for Experiment 2."""
from __future__ import annotations
import hashlib, json, shutil, sys, time
from pathlib import Path
from typing import Any
import yaml
from synthran.deployment_state import content_hash
from synthran.workload.bundle import canonical, read_events, validate_bundle, write_manifest
from . import source as source_cohort
from .common import ROOT, RUNTIME, _read_json, _write_json, _sha256, _run, _prepared, _deployment_roles
from .traffic import _ssh, _transport_value

def _verify_current_profile(deployment: dict[str, Any]) -> None:
    name = deployment.get("network_profile")
    path = ROOT / "deployment/group_vars/all" / f"network_profile_{name}.yaml"
    if not path.is_file():
        raise RuntimeError(f"active deployment network profile is unavailable in this checkout: {name}")
    profile = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(profile, dict):
        raise RuntimeError("current network profile is invalid")
    profile.pop("ues", None)
    expected = deployment.get("network_profile_hash")
    if expected and content_hash(profile) != expected:
        raise RuntimeError(
            "current checkout network profile differs from the profile used by the accepted deployment; "
            "redeploy or restore the matching checkout before running the experiment"
        )


def _base_testbed_config(root: Path, environment: dict[str, Any]) -> Path:
    path = root / "control/testbed.yml"
    snapshot = root / "control/deployment.json"
    if path.is_file() and snapshot.is_file():
        saved = _read_json(snapshot)
        if saved.get("deployment_hash") != environment["deployment_hash"]:
            raise RuntimeError("Experiment-2 campaign is bound to another deployment")
        return path

    deployment = environment["deployment"]
    _verify_current_profile(deployment)
    bindings = deployment.get("ues", [])
    names = [str(item["device"]) for item in bindings]
    assignments = {str(item["device"]): str(item["slice"]) for item in bindings}
    selected = {
        "core": deployment["core"],
        "ran": deployment["ran"],
        "platform": deployment["platform"],
        "nodes": deployment["nodes"],
        "network_profile": deployment["network_profile"],
        "bridge_enabled": bool(deployment.get("bridge_enabled", True)),
        "ues": names,
        "ue_slices": assignments,
    }
    if deployment["platform"] == "r2lab":
        selected["ru"] = deployment["radio_unit"]
    wrapper = {
        "deployment": selected,
        "experiment": {
            "entrypoint": str(RUNTIME.resolve()),
            "config": str((root / "control/science-placeholder.yml").resolve()),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(wrapper, sort_keys=False), encoding="utf-8")
    _write_json(
        snapshot,
        {
            "deployment_hash": environment["deployment_hash"],
            "deployment_run_id": environment["attachment"].get("deployment_run_id"),
            "deployment": deployment,
            "roles": {
                "workload_ue": names[0],
                "competing_ue": names[1],
            },
        },
    )
    shutil.copyfile(environment["attachment"]["identity_file"], root / "control/deployment-fingerprint.json")
    shutil.copyfile(environment["attachment"]["evidence_file"], root / "control/live-deployment-evidence.json")
    return path


def _remap_bundle(source: Path, destination: Path, gateway: str, deployment_hash: str) -> Path:
    if (destination / "source-manifest.json").is_file():
        validate_bundle(destination)
        return destination
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite incomplete execution bundle: {destination}")
    manifest = validate_bundle(source)
    shutil.copytree(source, destination)
    scenario_path = destination / "resolved-scenario.yml"
    scenario = yaml.safe_load(scenario_path.read_text(encoding="utf-8")) or {}
    devices = scenario.get("devices")
    if not isinstance(devices, dict):
        raise RuntimeError("prepared Experiment-2 bundle has no device mapping")
    for device in devices.values():
        device["gateway"] = gateway
    scenario["gateways"] = [gateway]
    scenario_path.write_text(yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8")

    event_path = destination / "events.jsonl"
    rows = read_events(event_path)
    with event_path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            changed = dict(row)
            changed["gateway"] = gateway
            stream.write(canonical(changed).decode("utf-8") + "\n")

    metadata = {
        key: value
        for key, value in manifest.items()
        if key not in {"files", "bundle_sha256", "sensor_gateways"}
    }
    metadata["sensor_gateways"] = {name: gateway for name in devices}
    metadata["transport_mapping"] = {
        "deployment_hash": deployment_hash,
        "gateway": gateway,
        "source_bundle_sha256": manifest["bundle_sha256"],
    }
    write_manifest(destination, metadata)
    validate_bundle(destination)
    return destination


def _bundle(root: Path, environment: dict[str, Any], seed: int, arm: str) -> Path:
    prepared_root, _ = _prepared()
    source = prepared_root / f"seed{seed:05d}" / arm / "model"
    validate_bundle(source)
    workload, _ = _deployment_roles(environment)
    destination = root / "inputs" / f"seed{seed:05d}" / arm / "model"
    return _remap_bundle(
        source,
        destination,
        str(workload["device"]),
        str(environment["deployment_hash"]),
    )


def _clock_target(environment: dict[str, Any], binding: dict[str, Any]) -> str:
    if environment["deployment"]["platform"] == "r2lab":
        return str(_transport_value(binding, "host") or binding["device"])
    return str(environment["deployment"]["nodes"]["ran"])


def _clock_interval(environment: dict[str, Any], host: str, samples: int = 12) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    for _ in range(samples):
        start = time.time()
        process = _ssh(environment, host, "date +%s.%N", capture=True)
        end = time.time()
        lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
        if not lines:
            continue
        try:
            remote = float(lines[-1])
        except ValueError:
            continue
        candidate = {
            "rtt_seconds": end - start,
            "offset_lower_seconds": remote - end,
            "offset_upper_seconds": remote - start,
        }
        if best is None or candidate["rtt_seconds"] < best["rtt_seconds"]:
            best = candidate
    if best is None:
        raise RuntimeError(f"could not collect clock evidence from {host}")
    sync = _ssh(
        environment,
        host,
        "timedatectl show -p NTPSynchronized --value 2>/dev/null || true",
        capture=True,
        check=False,
    ).stdout.strip()
    best["host"] = host
    best["ntp_synchronized"] = sync.lower() == "yes"
    return best


def _clock_evidence(root: Path, environment: dict[str, Any], label: str) -> dict[str, Any]:
    path = root / "clock" / f"{label}.json"
    if path.is_file():
        return _read_json(path)
    workload, _ = _deployment_roles(environment)
    broker_host = str(environment["deployment"]["nodes"]["broker"])
    publisher_host = _clock_target(environment, workload)
    publisher = _clock_interval(environment, publisher_host)
    broker = _clock_interval(environment, broker_host)
    lower = float(publisher["offset_lower_seconds"]) - float(broker["offset_upper_seconds"])
    upper = float(publisher["offset_upper_seconds"]) - float(broker["offset_lower_seconds"])
    bound = max(abs(lower), abs(upper))
    record = {
        "schema_version": 1,
        "method": "controller-bracketed remote UTC probes; interval bound does not assume symmetric network delay",
        "publisher": publisher,
        "broker": broker,
        "publisher_minus_broker_interval_seconds": [lower, upper],
        "clock_uncertainty_seconds": bound,
    }
    _write_json(path, record)
    return record


def _science_config(bundle: Path, destination: Path, manifest: dict[str, Any], clock_uncertainty: float) -> Path:
    scenario = yaml.safe_load((bundle / "resolved-scenario.yml").read_text(encoding="utf-8")) or {}
    if not isinstance(scenario, dict):
        raise RuntimeError("execution bundle scenario is invalid")
    study = manifest["study"]
    measurement = study["measurement"]
    scenario["measurement"] = {
        "warmup_seconds": float(study["timing"]["warmup_seconds"]),
        "deadline_seconds": float(measurement["deadline_seconds"]),
        "age_limit_seconds": float(measurement["age_limit_seconds"]),
        "clock_uncertainty_seconds": float(clock_uncertainty),
    }
    scenario.setdefault("mqtt", {})["drain_seconds"] = max(
        float(scenario.get("mqtt", {}).get("drain_seconds", 60)),
        float(measurement["deadline_seconds"]),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8")
    return destination


def _run_config(base_config: Path, run_dir: Path, bundle: Path, manifest: dict[str, Any], clock_uncertainty: float) -> Path:
    wrapper = yaml.safe_load(base_config.read_text(encoding="utf-8")) or {}
    science = _science_config(
        bundle,
        run_dir / "scientific-config.yml",
        manifest,
        clock_uncertainty,
    )
    wrapper["experiment"]["config"] = str(science.resolve())
    config = run_dir / "testbed.yml"
    run_dir.mkdir(parents=True, exist_ok=True)
    config.write_text(yaml.safe_dump(wrapper, sort_keys=False), encoding="utf-8")
    return config


def _runtime_phase(phase: str, config: Path, run_dir: Path, bundle: Path | None = None) -> None:
    command: list[str | Path] = [
        sys.executable,
        RUNTIME,
        phase,
        "--config",
        config,
        "--run-dir",
        run_dir,
    ]
    if phase == "prepare" and bundle is not None:
        command.extend(["--prepared-workload", bundle])
    _run(command)


def _victim_run(root: Path, environment: dict[str, Any], manifest: dict[str, Any], bundle: Path, run_dir: Path, *, clock_uncertainty: float) -> dict[str, Any]:
    summary = run_dir / "summary.json"
    if summary.is_file():
        return _read_json(summary)
    base_config = _base_testbed_config(root, environment)
    config = _run_config(base_config, run_dir, bundle, manifest, clock_uncertainty)
    _runtime_phase("prepare", config, run_dir, bundle)
    shutil.copyfile(environment["attachment"]["identity_file"], run_dir / "deployment-fingerprint.json")
    shutil.copyfile(environment["attachment"]["evidence_file"], run_dir / "live-deployment-evidence.json")
    succeeded = False
    try:
        _runtime_phase("run", config, run_dir)
        _runtime_phase("finalize", config, run_dir)
        succeeded = True
    finally:
        try:
            _runtime_phase("cleanup", config, run_dir)
        except Exception:
            if succeeded:
                raise
    if not summary.is_file():
        raise RuntimeError(f"experiment runtime produced no summary: {run_dir}")
    return _read_json(summary)


def _prepared_seeds() -> list[int]:
    _, index = _prepared()
    return sorted(int(row["seed"]) for row in index["sources"])
