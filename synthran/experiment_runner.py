#!/usr/bin/env python3
"""Reusable Ambient-IoT experiment lifecycle for an accepted SynthRAN testbed."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

from synthran.experiment_scenario import load_scenario, remap_gateways, scientific_settings
from synthran.scenario import load_scenario as load_testbed

ACTIVE_DEPLOYMENT_ENDPOINT = ROOT / ".synthran/active-deployment.json"
EXPERIMENT_ANSIBLE = ROOT / "synthran/experiment_runtime/ansible"


def _active_private_dir() -> Path:
    configured = os.environ.get("SYNTHRAN_PRIVATE_DIR")
    if configured:
        private = Path(configured).resolve()
    else:
        if not ACTIVE_DEPLOYMENT_ENDPOINT.is_file():
            raise FileNotFoundError(
                "no accepted deployment endpoint exists; run ./deploy.sh successfully first"
            )
        endpoint = json.loads(ACTIVE_DEPLOYMENT_ENDPOINT.read_text(encoding="utf-8"))
        if endpoint.get("status") != "active":
            raise ValueError("the saved deployment endpoint is not active")
        identity_path = Path(endpoint.get("identity_file", ""))
        if not identity_path.is_file():
            raise FileNotFoundError("the active deployment identity referenced by the endpoint is missing")
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        if identity.get("status") != "active" or identity.get("deployment_hash") != endpoint.get("deployment_hash"):
            raise ValueError("the active deployment endpoint does not match the active deployment identity")
        private = Path(endpoint.get("private_execution_dir", "")).resolve()
        os.environ["SYNTHRAN_PRIVATE_DIR"] = str(private)
    required = (private / "inventory.yml", private / "deployment-vars.yml")
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "the accepted deployment execution context is incomplete: " + ", ".join(missing)
        )
    return private


def _configure_source(source: Path) -> dict:
    """Load either a full experiment scenario or standalone scientific settings."""
    raw = yaml.safe_load(source.read_text())
    if not isinstance(raw, dict):
        raise ValueError("experiment configuration must be a mapping")
    if "deployment" in raw:
        return load_scenario(source)

    for section in ("model", "mqtt", "devices"):
        if not isinstance(raw.get(section), dict):
            raise ValueError(f"experiment settings require mapping: {section}")
    if not raw["devices"]:
        raise ValueError("devices must define at least one sensor")

    logical_gateways = []
    for name, device in raw["devices"].items():
        if not isinstance(device, dict):
            raise ValueError("devices must map sensor names to configurations")
        gateway = device.get("gateway", name)
        device["gateway"] = gateway
        if gateway not in logical_gateways:
            logical_gateways.append(gateway)
    raw["deployment"] = {"ues": logical_gateways}

    trace = raw["model"].get("energy", {}).get("trace")
    if trace and not str(trace).startswith("builtin:"):
        raw["model"]["energy"]["trace"] = str((source.resolve().parent / trace).resolve())
    for device in raw["devices"].values():
        trace = device.get("energy", {}).get("trace")
        if trace and not str(trace).startswith("builtin:"):
            device["energy"]["trace"] = str((source.resolve().parent / trace).resolve())
    return raw


def configure(config: Path, source: Path) -> None:
    original = _configure_source(source)
    selected = load_testbed(config)
    remap_gateways(original, selected["deployment"]["ues"])
    settings = config.with_name("selected-experiment.yml")
    settings.write_text(
        yaml.safe_dump(scientific_settings(original), sort_keys=False)
    )
    selected["experiment"]["config"] = str(settings.resolve())
    selected.pop("_source_directory", None)
    config.write_text(yaml.safe_dump(selected, sort_keys=False))


def prepare(
    config: Path, run: Path, prepared: Path | None, resume: Path | None
) -> None:
    from synthran.runtime import ensure

    ensure("experiment", run / "experiment-bootstrap.log")
    from synthran.mqtt_auth import write_credentials
    from synthran.workload.bundle import import_bundle
    from synthran.workload.trace import generate

    scenario = load_scenario(config)
    run.mkdir(parents=True, exist_ok=True)
    private = _active_private_dir()
    write_credentials(private)
    settings = run / "experiment-input.yml"
    settings.write_text(
        yaml.safe_dump(scientific_settings(scenario), sort_keys=False)
    )
    testbed = load_testbed(config)
    testbed["experiment"]["config"] = str(settings.resolve())
    testbed.pop("_source_directory", None)
    config.write_text(yaml.safe_dump(testbed, sort_keys=False))
    snapshot = run / "experiment-scenario.yml"
    scenario.pop("_source_directory", None)
    scenario.pop("experiment", None)
    snapshot.write_text(yaml.safe_dump(scenario, sort_keys=False))
    if resume:
        prepared = resume / "model"
    if prepared:
        import_bundle(prepared, run / "model", snapshot)
    else:
        generate(snapshot, run / "model")
    for relative in (
        "__init__.py",
        "cli.py",
        "workload/__init__.py",
        "workload/replay.py",
        "workload/bundle.py",
        "workload/cleanup.py",
    ):
        destination = run / "runtime/synthran" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).parent / relative, destination)
    mqtt = scenario["mqtt"]
    manifest = json.loads((run / "model/source-manifest.json").read_text())
    variables = {
        "mqtt_start_delay_seconds": mqtt.get("start_delay_seconds", 30),
        "mqtt_broker_address": mqtt.get("broker_address"),
        "mqtt_port": mqtt.get("port", 1883),
        "mqtt_qos": mqtt.get("qos", 1),
        "mqtt_topic_prefix": mqtt.get("topic_prefix", "synthran"),
        "mqtt_drain_seconds": mqtt.get("drain_seconds", 60),
        "mqtt_max_inflight": mqtt.get("max_inflight", 20),
        "mqtt_max_queued": mqtt.get("max_queued", 10000),
        "synthran_replay_horizon_seconds": manifest["duration_seconds"],
    }
    (run / "experiment-vars.yml").write_text(yaml.safe_dump(variables, sort_keys=False))


def _run_playbook(run: Path, playbook: Path) -> None:
    environment = dict(os.environ)
    environment["ANSIBLE_CONFIG"] = str(ROOT / "deployment/ansible.cfg")
    environment["ANSIBLE_ROLES_PATH"] = str(EXPERIMENT_ANSIBLE / "roles")
    private = _active_private_dir()
    environment["SYNTHRAN_PRIVATE_DIR"] = str(private)
    secrets_file = private / "experiment-secrets.yml"
    if not secrets_file.is_file():
        raise FileNotFoundError("private MQTT credentials are missing; prepare the experiment first")
    executable = Path(sys.executable).with_name("ansible-playbook")
    command = [
        str(executable),
        "-i",
        str(private / "inventory.yml"),
        "-e",
        "@" + str(ROOT / "deployment/group_vars/all/all.yml"),
        "-e",
        "@" + str(private / "deployment-vars.yml"),
        "-e",
        "@" + str(run / "experiment-vars.yml"),
        "-e",
        "@" + str(secrets_file),
        str(playbook),
    ]
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


def run_workload(run: Path) -> None:
    _run_playbook(run, EXPERIMENT_ANSIBLE / "playbooks/mqtt.yml")


def cleanup(run: Path) -> None:
    _run_playbook(run, EXPERIMENT_ANSIBLE / "playbooks/cleanup.yml")


def finalize(run: Path) -> None:
    from synthran.results import reconcile

    publishers = run / "publisher.jsonl"
    sources = [
        source
        for source in sorted(run.glob("publisher-*.jsonl"))
        if source != publishers
    ]
    partial = run / "partial-software-publishers.jsonl"
    if partial.is_file():
        sources.append(partial)

    seen: set[str] = set()
    with publishers.open("w") as stream:
        for source in sources:
            for line in source.read_text().splitlines():
                if not line.strip() or line in seen:
                    continue
                seen.add(line)
                stream.write(line + "\n")
    summary = reconcile(
        run / "model/events.jsonl",
        publishers,
        run / "broker.jsonl",
        run / "summary.json",
        run / "experiment-scenario.yml",
        True,
    )
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase", choices=("configure", "prepare", "run", "cleanup", "finalize")
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--prepared-workload", type=Path)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--source-config", type=Path)
    args = parser.parse_args()
    if args.phase == "configure":
        if not args.source_config:
            parser.error("configure requires --source-config")
        configure(args.config, args.source_config)
    else:
        if not args.run_dir:
            parser.error(f"{args.phase} requires --run-dir")
        run = args.run_dir.resolve()
        if args.phase == "prepare":
            prepare(args.config, run, args.prepared_workload, args.resume_from)
        elif args.phase == "run":
            run_workload(run)
        elif args.phase == "cleanup":
            cleanup(run)
        else:
            finalize(run)


if __name__ == "__main__":
    main()
