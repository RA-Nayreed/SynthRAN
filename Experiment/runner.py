#!/usr/bin/env python3
"""Ambient-IoT experiment lifecycle called by the generic testbed controller."""

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

from Experiment.scenario import load_scenario, remap_gateways, scientific_settings
from synthran.scenario import load_scenario as load_testbed


def configure(config: Path, source: Path) -> None:
    original = load_scenario(source)
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
    from Experiment.workload.bundle import import_bundle
    from Experiment.workload.trace import generate

    scenario = load_scenario(config)
    run.mkdir(parents=True, exist_ok=True)
    # Freeze scientific settings and resolve trace paths before any reservation.
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
        destination = run / "runtime/Experiment" / relative
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
    environment["ANSIBLE_ROLES_PATH"] = str(ROOT / "Experiment/deployment/roles")
    private = Path(environment["SYNTHRAN_PRIVATE_DIR"])
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
        str(playbook),
    ]
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


def run_workload(run: Path) -> None:
    _run_playbook(run, ROOT / "Experiment/deployment/playbooks/mqtt.yml")


def cleanup(run: Path) -> None:
    _run_playbook(run, ROOT / "Experiment/deployment/playbooks/cleanup.yml")


def finalize(run: Path) -> None:
    from Experiment.results import reconcile

    publishers = run / "publisher.jsonl"
    sources = [
        source
        for source in sorted(run.glob("publisher-*.jsonl"))
        if source != publishers
    ]
    partial = run / "partial-software-publishers.jsonl"
    if partial.is_file():
        sources.append(partial)

    # Cleanup may recover records already fetched by the successful path.
    # Deduplicate exact append-only records while preserving source order.
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
