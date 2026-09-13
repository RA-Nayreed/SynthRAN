#!/usr/bin/env python3
"""Run the complete Experiment-2 causal 5G transport campaign on an accepted testbed."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shlex
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from synthran.archive import archive_directory
from synthran.scenario import load_scenario as load_testbed
from synthran.testbed_attachment import attach_active_deployment, requirements_from_deployment
from synthran.workload.bundle import validate_bundle

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_PLAN = HERE / "experiment-plan.json"
RUNTIME = ROOT / "synthran/experiment_runtime/runner.py"
ACTIVE = ROOT / ".synthran/active-ex2.json"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _source_revision() -> str:
    p = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return p.stdout.strip() if p.returncode == 0 else "unknown"


def _run(command: list[str | Path], *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [str(value) for value in command]
    print("$ " + " ".join(shlex.quote(value) for value in cmd), flush=True)
    p = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=capture,
        check=False,
    )
    if capture and p.stdout:
        print(p.stdout, end="" if p.stdout.endswith("\n") else "\n")
    if p.returncode and check:
        if capture and p.stderr:
            print(p.stderr, file=sys.stderr)
        raise RuntimeError(f"command failed with exit {p.returncode}: {cmd[0]}")
    return p


def _new_campaign(plan: dict[str, Any], prepared_root: Path, profile: str) -> Path:
    campaign_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = ROOT / "results/experiments/ex2" / campaign_id
    root.mkdir(parents=True)
    prepared_index = _read_json(prepared_root / "prepared-index.json")
    campaign = {
        "schema_version": 1,
        "experiment": "ex2",
        "campaign_id": campaign_id,
        "status": "active",
        "source_revision": _source_revision(),
        "design_plan_sha256": hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "upstream_campaign_id": prepared_index["upstream_campaign_id"],
        "upstream_frozen_design_sha256": prepared_index["upstream_frozen_design_sha256"],
        "prepared_index_sha256": _sha256(prepared_root / "prepared-index.json"),
        "transport_profile": profile,
        "completed_sessions": [],
        "completed_phases": [],
    }
    _write_json(root / "campaign.json", campaign)
    _write_json(root / "plan-snapshot.json", plan)
    _write_json(
        ACTIVE,
        {
            "schema_version": 1,
            "status": "active",
            "campaign_root": str(root.resolve()),
            "campaign_id": campaign_id,
        },
    )
    return root


def _campaign_root(plan: dict[str, Any], prepared_root: Path, profile: str, supplied: Path | None) -> Path:
    if supplied:
        root = supplied.expanduser().resolve()
        campaign = _read_json(root / "campaign.json")
        if campaign.get("experiment") != "ex2":
            raise ValueError("campaign root is not Experiment 2")
        return root
    if ACTIVE.is_file():
        active = _read_json(ACTIVE)
        candidate = Path(str(active.get("campaign_root", ""))).resolve()
        if active.get("status") == "active" and (candidate / "campaign.json").is_file():
            campaign = _read_json(candidate / "campaign.json")
            if campaign.get("status") == "active" and campaign.get("transport_profile") == profile:
                return candidate
    return _new_campaign(plan, prepared_root, profile)


def _mark(root: Path, *, phase: str | None = None, session: int | None = None, complete: bool = False) -> None:
    path = root / "campaign.json"
    value = _read_json(path)
    if phase and phase not in value["completed_phases"]:
        value["completed_phases"].append(phase)
    if session is not None and session not in value["completed_sessions"]:
        value["completed_sessions"].append(session)
        value["completed_sessions"].sort()
    if complete:
        value["status"] = "complete"
        value["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(path, value)
    if complete and ACTIVE.is_file():
        active = _read_json(ACTIVE)
        if active.get("campaign_id") == value["campaign_id"]:
            active["status"] = "complete"
            _write_json(ACTIVE, active)


def _transport_value(binding: dict[str, Any], key: str) -> Any:
    if key in binding:
        return binding.get(key)
    tunnel = binding.get("tunnel", {})
    return tunnel.get(key) if isinstance(tunnel, dict) else None


def _attachment(config: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = load_testbed(config)
    attachment = attach_active_deployment(
        requirements_from_deployment(scenario["deployment"])
    )
    evidence = _read_json(Path(attachment["evidence_file"]))
    return attachment, evidence


def _binding(evidence: dict[str, Any], device: str) -> dict[str, Any]:
    items = [item for item in evidence.get("bindings", []) if item.get("device") == device]
    if len(items) != 1:
        raise ValueError(f"expected exactly one live binding for {device}; got {len(items)}")
    return items[0]


def _broker_address(host: str) -> str:
    p = _run(
        [
            "ssh",
            host,
            "ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i==\"src\") {print $(i+1); exit}}'",
        ],
        capture=True,
    )
    lines = [line.strip() for line in p.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"could not determine broker IPv4 address on {host}")
    return lines[-1]


def _stage_udp_tools(profile: dict[str, Any], competitor: dict[str, Any]) -> None:
    broker = str(profile["nodes"]["broker"])
    ran = str(profile["nodes"]["ran"])
    _run(["scp", HERE / "udp_receiver.py", f"{broker}:/tmp/exp2_udp_receiver.py"])
    if profile["platform"] == "r2lab":
        host = str(_transport_value(competitor, "host") or competitor["device"])
        _run(["scp", HERE / "udp_sender.py", f"{host}:/tmp/exp2_udp_sender.py"])
        return
    _run(["scp", HERE / "udp_sender.py", f"{ran}:/tmp/exp2_udp_sender.py"])
    namespace = str(_transport_value(competitor, "namespace"))
    pod = str(competitor.get("pod") or competitor.get("pod_name"))
    container = str(competitor.get("container") or "synthran-runtime")
    if not namespace or namespace == "None" or not pod or pod == "None":
        raise RuntimeError("software-UE live evidence lacks namespace/pod information")
    remote = (
        f"kubectl cp -n {shlex.quote(namespace)} -c {shlex.quote(container)} "
        f"/tmp/exp2_udp_sender.py {shlex.quote(pod)}:/tmp/exp2_udp_sender.py"
    )
    _run(["ssh", ran, remote])


def _prove_competitor_route(
    profile: dict[str, Any], competitor: dict[str, Any], destination: str
) -> str:
    address = str(competitor.get("address") or "")
    interface = str(_transport_value(competitor, "interface") or "")
    if not address or not interface:
        raise RuntimeError("competing UE live evidence lacks address/interface")
    if profile["platform"] == "r2lab":
        host = str(_transport_value(competitor, "host") or competitor["device"])
        p = _run(
            ["ssh", host, f"ip route get {shlex.quote(destination)} from {shlex.quote(address)}"],
            capture=True,
        )
    else:
        ran = str(profile["nodes"]["ran"])
        namespace = str(_transport_value(competitor, "namespace"))
        pod = str(competitor.get("pod") or competitor.get("pod_name"))
        container = str(competitor.get("container") or "synthran-runtime")
        remote = (
            f"kubectl exec -n {shlex.quote(namespace)} {shlex.quote(pod)} "
            f"-c {shlex.quote(container)} -- "
            f"ip route get {shlex.quote(destination)} from {shlex.quote(address)}"
        )
        p = _run(["ssh", ran, remote], capture=True)
    if interface not in p.stdout or f"from {address}" not in p.stdout:
        raise RuntimeError("competing traffic is not routed through its assigned 5G tunnel")
    return p.stdout.strip()


def _sender_command(
    profile: dict[str, Any],
    competitor: dict[str, Any],
    destination: str,
    *,
    rate: float,
    seconds: float,
    packet_bytes: int,
    port: int,
) -> list[str]:
    address = str(competitor["address"])
    args = (
        f"python3 /tmp/exp2_udp_sender.py --destination {shlex.quote(destination)} "
        f"--port {port} --bind-address {shlex.quote(address)} "
        f"--rate-mbps {rate:g} --duration-seconds {seconds:g} --packet-bytes {packet_bytes}"
    )
    if profile["platform"] == "r2lab":
        host = str(_transport_value(competitor, "host") or competitor["device"])
        return ["ssh", "-n", host, args]
    ran = str(profile["nodes"]["ran"])
    namespace = str(_transport_value(competitor, "namespace"))
    pod = str(competitor.get("pod") or competitor.get("pod_name"))
    container = str(competitor.get("container") or "synthran-runtime")
    remote = (
        f"kubectl exec -n {shlex.quote(namespace)} {shlex.quote(pod)} "
        f"-c {shlex.quote(container)} -- {args}"
    )
    return ["ssh", "-n", ran, remote]


def _json_line(text: str) -> dict[str, Any]:
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError("expected JSON output was not found")


def _start_background(
    profile: dict[str, Any],
    competitor: dict[str, Any],
    destination: str,
    *,
    rate: float,
    seconds: float,
    packet_bytes: int,
    port: int,
) -> tuple[subprocess.Popen, subprocess.Popen]:
    broker = str(profile["nodes"]["broker"])
    receiver = subprocess.Popen(
        [
            "ssh",
            "-n",
            broker,
            f"python3 /tmp/exp2_udp_receiver.py --port {port} "
            "--startup-timeout-seconds 30 --idle-timeout-seconds 3",
        ],
        cwd=ROOT,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(0.75)
    sender = subprocess.Popen(
        _sender_command(
            profile,
            competitor,
            destination,
            rate=rate,
            seconds=seconds,
            packet_bytes=packet_bytes,
            port=port,
        ),
        cwd=ROOT,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return sender, receiver


def _finish_background(
    sender: subprocess.Popen, receiver: subprocess.Popen, timeout: float
) -> dict[str, Any]:
    sout, serr = sender.communicate(timeout=timeout)
    rout, rerr = receiver.communicate(timeout=15)
    if sender.returncode:
        raise RuntimeError(f"background sender failed: {serr.strip()}")
    if receiver.returncode:
        raise RuntimeError(f"background receiver failed: {rerr.strip()}")
    tx, rx = _json_line(sout), _json_line(rout)
    sent = int(tx["packets_attempted"])
    received = int(rx["packets_received"])
    return {
        "sender": tx,
        "receiver": rx,
        "packets_attempted": sent,
        "packets_received": received,
        "packets_lost": max(sent - received, 0),
        "delivery_ratio": received / sent if sent else 0.0,
    }


def _udp_probe(
    profile: dict[str, Any],
    competitor: dict[str, Any],
    destination: str,
    *,
    rate: float,
    seconds: float,
    packet_bytes: int,
    port: int,
) -> dict[str, Any]:
    sender, receiver = _start_background(
        profile,
        competitor,
        destination,
        rate=rate,
        seconds=seconds,
        packet_bytes=packet_bytes,
        port=port,
    )
    return _finish_background(sender, receiver, seconds + 30)


def _run_config(base_config: Path, run_dir: Path, clock_uncertainty: float) -> Path:
    wrapper = yaml.safe_load(base_config.read_text(encoding="utf-8"))
    source_science = Path(wrapper["experiment"]["config"])
    science = yaml.safe_load(source_science.read_text(encoding="utf-8"))
    science.setdefault("measurement", {})["clock_uncertainty_seconds"] = float(clock_uncertainty)
    science_path = run_dir / "scientific-config.yml"
    config_path = run_dir / "transport.yml"
    run_dir.mkdir(parents=True, exist_ok=True)
    science_path.write_text(yaml.safe_dump(science, sort_keys=False), encoding="utf-8")
    wrapper["experiment"]["config"] = str(science_path.resolve())
    config_path.write_text(yaml.safe_dump(wrapper, sort_keys=False), encoding="utf-8")
    return config_path


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
        command += ["--prepared-workload", bundle]
    _run(command)


def _victim_run(
    base_config: Path,
    bundle: Path,
    run_dir: Path,
    *,
    clock_uncertainty: float,
) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if summary_path.is_file():
        return _read_json(summary_path)
    config = _run_config(base_config, run_dir, clock_uncertainty)
    _runtime_phase("prepare", config, run_dir, bundle)
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
    if not summary_path.is_file():
        raise RuntimeError(f"experiment runtime produced no summary: {run_dir}")
    return _read_json(summary_path)


def _prepared_seeds(prepared_root: Path) -> list[int]:
    index = _read_json(prepared_root / "prepared-index.json")
    return sorted(int(row["seed"]) for row in index["sources"])


def _bundle(prepared_root: Path, seed: int, arm: str) -> Path:
    path = prepared_root / f"seed{seed:05d}" / arm / "model"
    validate_bundle(path)
    return path


def _qualification(
    campaign_root: Path,
    base_config: Path,
    prepared_root: Path,
    plan: dict[str, Any],
    clock_uncertainty: float,
) -> dict[str, Any]:
    destination = campaign_root / "qualification/summary.json"
    if destination.is_file():
        return _read_json(destination)
    seed = _prepared_seeds(prepared_root)[0]
    run_dir = campaign_root / "qualification/native-no-load"
    summary = _victim_run(
        base_config,
        _bundle(prepared_root, seed, "native"),
        run_dir,
        clock_uncertainty=clock_uncertainty,
    )
    coverage = summary.get("experimental_coverage", {})
    if (
        plan["qualification"]["require_zero_transport_loss"]
        and coverage.get("transport_loss_observed") is not False
    ):
        raise RuntimeError("Experiment-2 no-load qualification observed transport loss")
    result = {
        "schema_version": 1,
        "status": "passed",
        "source_seed": seed,
        "deployment_identity": summary.get("deployment_identity"),
        "measurement": summary.get("measurement"),
        "five_g": summary.get("five_g"),
        "experimental_coverage": coverage,
    }
    _write_json(destination, result)
    return result


def _transport_context(
    base_config: Path, plan: dict[str, Any], profile_name: str
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    profile = plan["transport_profiles"][profile_name]
    _, evidence = _attachment(base_config)
    competitor = _binding(evidence, str(profile["competing_traffic_ue"]))
    destination = _broker_address(str(profile["nodes"]["broker"]))
    _stage_udp_tools(profile, competitor)
    route = _prove_competitor_route(profile, competitor, destination)
    return profile, competitor, destination, route


def _calibrate(
    campaign_root: Path,
    base_config: Path,
    plan: dict[str, Any],
    profile_name: str,
) -> dict[str, Any]:
    destination = campaign_root / "calibration/load-selection.json"
    if destination.is_file():
        return _read_json(destination)
    profile, competitor, broker, route = _transport_context(base_config, plan, profile_name)
    cal = plan["transport_calibration"]
    rates = [float(value) for value in cal["offered_payload_mbps_grid"]]
    repeats = int(cal["repeats_per_rate"])
    threshold = float(cal["delivery_threshold"])
    seconds = float(cal["probe_duration_seconds"])
    packet_bytes = int(cal["packet_bytes"])
    base_port = int(cal["base_port"])
    records = []
    medians = []
    for rate_index, rate in enumerate(rates):
        ratios = []
        for repeat in range(repeats):
            port = base_port + rate_index * repeats + repeat
            probe = _udp_probe(
                profile,
                competitor,
                broker,
                rate=rate,
                seconds=seconds,
                packet_bytes=packet_bytes,
                port=port,
            )
            probe.update({"rate_mbps": rate, "repeat": repeat + 1, "port": port})
            ratios.append(float(probe["delivery_ratio"]))
            records.append(probe)
            print(
                f"Calibration {rate:g} Mbps repeat {repeat+1}/{repeats}: "
                f"delivery={probe['delivery_ratio']:.6f}",
                flush=True,
            )
        medians.append(statistics.median(ratios))

    crossing = next((i for i, value in enumerate(medians) if value < threshold), None)
    if crossing is None or crossing < 2:
        raise RuntimeError(
            "formal load calibration could not select BELOW/NEAR/ABOVE by the frozen rule"
        )
    selected = {
        "below": rates[crossing - 2],
        "near": rates[crossing - 1],
        "above": rates[crossing],
    }
    result = {
        "schema_version": 1,
        "status": "selected",
        "selection_rule": cal["selection_rule"],
        "delivery_threshold": threshold,
        "route_evidence": route,
        "broker_address": broker,
        "selected_mbps": selected,
        "rate_medians": [
            {"rate_mbps": rate, "median_delivery_ratio": median}
            for rate, median in zip(rates, medians)
        ],
        "probes": records,
    }
    _write_json(destination, result)
    return result


def _session_seeds(seeds: list[int], plan: dict[str, Any], session: int) -> list[int]:
    sessions = int(plan["confirmation"]["sessions"])
    per = int(plan["confirmation"]["seeds_per_session"])
    if len(seeds) != sessions * per:
        raise RuntimeError("source-seed count does not match the frozen session design")
    if not 1 <= session <= sessions:
        raise ValueError(f"session must be in 1..{sessions}")
    return seeds[(session - 1) * per : session * per]


def _confirmation_order(
    seeds: list[int],
    loads: list[str],
    arms: list[str],
    *,
    campaign_id: str,
    session: int,
    order_seed: int,
) -> list[tuple[int, str, str]]:
    blocks = [(seed, load) for seed in seeds for load in loads]
    rng = random.Random(
        int.from_bytes(
            hashlib.sha256(
                f"{campaign_id}|{session}|{order_seed}".encode("utf-8")
            ).digest()[:8],
            "big",
        )
    )
    rng.shuffle(blocks)
    order = []
    for seed, load in blocks:
        local = list(arms)
        block_seed = int.from_bytes(
            hashlib.sha256(
                f"{campaign_id}|{session}|{seed}|{load}|{order_seed}".encode("utf-8")
            ).digest()[:8],
            "big",
        )
        random.Random(block_seed).shuffle(local)
        order.extend((seed, load, arm) for arm in local)
    return order


def _background_seconds(bundle: Path) -> float:
    manifest = validate_bundle(bundle)
    scenario = yaml.safe_load((bundle / "resolved-scenario.yml").read_text(encoding="utf-8"))
    mqtt = scenario.get("mqtt", {})
    return (
        float(manifest["duration_seconds"])
        + float(mqtt.get("start_delay_seconds", 30))
        + float(mqtt.get("drain_seconds", 60))
        + 30.0
    )


def _sentinel(
    campaign_root: Path,
    plan: dict[str, Any],
    profile: dict[str, Any],
    competitor: dict[str, Any],
    broker: str,
    calibration: dict[str, Any],
    *,
    session: int,
    ordinal: int,
) -> dict[str, Any]:
    cal = plan["transport_calibration"]
    near = float(calibration["selected_mbps"]["near"])
    near_median = next(
        float(row["median_delivery_ratio"])
        for row in calibration["rate_medians"]
        if math.isclose(float(row["rate_mbps"]), near)
    )
    minimum = near_median * float(
        plan["confirmation"]["sentinel_min_fraction_of_calibrated_near_delivery"]
    )
    port = int(plan["confirmation"]["sentinel_base_port"]) + session * 100 + ordinal
    probe = _udp_probe(
        profile,
        competitor,
        broker,
        rate=near,
        seconds=float(cal["probe_duration_seconds"]),
        packet_bytes=int(cal["packet_bytes"]),
        port=port,
    )
    record = {
        "session": session,
        "after_replay": ordinal,
        "rate_mbps": near,
        "calibrated_near_median_delivery_ratio": near_median,
        "minimum_delivery_ratio": minimum,
        **probe,
    }
    path = campaign_root / "sentinels" / f"session{session}-after{ordinal:03d}.json"
    _write_json(path, record)
    if float(probe["delivery_ratio"]) < minimum:
        raise RuntimeError(
            "drift sentinel failed; preserve this session and diagnose before continuing"
        )
    return record


def _confirmation_session(
    campaign_root: Path,
    base_config: Path,
    prepared_root: Path,
    plan: dict[str, Any],
    profile_name: str,
    calibration: dict[str, Any],
    *,
    session: int,
    clock_uncertainty: float,
) -> None:
    seeds = _session_seeds(_prepared_seeds(prepared_root), plan, session)
    arms = list(plan["confirmation"]["timing_arms"])
    loads = list(plan["confirmation"]["load_levels"])
    campaign = _read_json(campaign_root / "campaign.json")
    order = _confirmation_order(
        seeds,
        loads,
        arms,
        campaign_id=campaign["campaign_id"],
        session=session,
        order_seed=int(plan["confirmation"]["within_block_order_seed"]),
    )
    session_root = campaign_root / f"sessions/session{session}"
    plan_path = session_root / "execution-plan.json"
    if not plan_path.is_file():
        _write_json(
            plan_path,
            {
                "schema_version": 1,
                "session": session,
                "source_seeds": seeds,
                "order": [
                    {"ordinal": i + 1, "seed": seed, "load": load, "arm": arm}
                    for i, (seed, load, arm) in enumerate(order)
                ],
            },
        )

    profile, competitor, broker, route = _transport_context(base_config, plan, profile_name)
    _write_json(
        session_root / "transport-context.json",
        {
            "route_evidence": route,
            "broker_address": broker,
            "competing_ue": competitor,
        },
    )
    packet_bytes = int(plan["transport_calibration"]["packet_bytes"])
    replay_base_port = int(plan["confirmation"]["base_port"]) + (session - 1) * 1000
    sentinel_every = int(plan["confirmation"]["sentinel_every_replays"])

    for ordinal, (seed, load, arm) in enumerate(order, start=1):
        name = f"s{session}-r{ordinal:03d}-seed{seed:05d}-{load}-{arm}"
        run_dir = campaign_root / "runs" / name
        record_path = run_dir / "run-record.json"
        if record_path.is_file():
            print(f"[{ordinal}/{len(order)}] {name} · reused", flush=True)
            continue

        bundle = _bundle(prepared_root, seed, arm)
        rate = float(calibration["selected_mbps"][load])
        seconds = _background_seconds(bundle)
        port = replay_base_port + ordinal
        sender, receiver = _start_background(
            profile,
            competitor,
            broker,
            rate=rate,
            seconds=seconds,
            packet_bytes=packet_bytes,
            port=port,
        )
        time.sleep(1.0)
        try:
            summary = _victim_run(
                base_config,
                bundle,
                run_dir,
                clock_uncertainty=clock_uncertainty,
            )
            background = _finish_background(sender, receiver, seconds + 30)
        except BaseException:
            for process in (sender, receiver):
                if process.poll() is None:
                    process.terminate()
            for process in (sender, receiver):
                try:
                    process.communicate(timeout=5)
                except Exception:
                    process.kill()
            raise

        record = {
            "schema_version": 1,
            "status": "complete",
            "session": session,
            "ordinal": ordinal,
            "seed": seed,
            "load_level": load,
            "background_rate_mbps": rate,
            "timing_arm": arm,
            "bundle_sha256": validate_bundle(bundle)["bundle_sha256"],
            "background": background,
            "deployment_identity": summary.get("deployment_identity"),
            "measurement": summary.get("measurement"),
            "five_g": summary.get("five_g"),
            "experimental_coverage": summary.get("experimental_coverage"),
        }
        _write_json(record_path, record)
        print(
            f"[{ordinal}/{len(order)}] {name} ✓ "
            f"bg_delivery={background['delivery_ratio']:.5f}",
            flush=True,
        )
        if ordinal % sentinel_every == 0 and ordinal < len(order):
            _sentinel(
                campaign_root,
                plan,
                profile,
                competitor,
                broker,
                calibration,
                session=session,
                ordinal=ordinal,
            )

    expected = len(seeds) * len(loads) * len(arms)
    records = list(campaign_root.glob("runs/s%d-r*-*/run-record.json" % session))
    if len(records) != expected:
        raise RuntimeError(f"session {session} has {len(records)}/{expected} completed replays")
    _write_json(
        session_root / "summary.json",
        {"schema_version": 1, "status": "complete", "session": session, "replays": expected},
    )
    _mark(campaign_root, session=session)


def _bootstrap(values: list[float], *, resamples: int, seed: int) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "ci95": [None, None]}
    observed = statistics.fmean(values)
    if len(values) == 1:
        return {"n": 1, "mean": observed, "ci95": [None, None]}
    rng = random.Random(seed)
    draws = sorted(
        statistics.fmean([values[rng.randrange(len(values))] for _ in values])
        for _ in range(resamples)
    )
    lo = int(0.025 * (len(draws) - 1))
    hi = int(0.975 * (len(draws) - 1))
    return {"n": len(values), "mean": observed, "ci95": [draws[lo], draws[hi]]}


def _analysis(campaign_root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    destination = campaign_root / "analysis/summary.json"
    if destination.is_file():
        return _read_json(destination)
    records = [_read_json(path) for path in sorted((campaign_root / "runs").glob("*/run-record.json"))]
    expected = int(plan["confirmation"]["expected_replays"])
    if len(records) != expected:
        raise RuntimeError(f"analysis requires {expected} completed replays; found {len(records)}")
    by_key = {
        (int(row["seed"]), row["load_level"], row["timing_arm"]): row
        for row in records
    }
    if len(by_key) != expected:
        raise RuntimeError("Experiment-2 confirmation contains duplicate treatment cells")

    outcomes = list(plan["analysis"]["principal_outcomes"])
    loads = list(plan["confirmation"]["load_levels"])
    seeds = sorted({int(row["seed"]) for row in records})
    resamples = int(plan["analysis"]["bootstrap_resamples"])
    master_seed = int(plan["analysis"]["bootstrap_seed"])
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "complete",
        "experimental_unit": "source_seed",
        "runs_analyzed": len(records),
        "source_seeds": seeds,
        "principal_contrasts": {},
    }
    for load in loads:
        load_result: dict[str, Any] = {}
        for outcome in outcomes:
            np_values, nr_values, excluded = [], [], []
            for seed in seeds:
                rows = {
                    arm: by_key[(seed, load, arm)]
                    for arm in plan["confirmation"]["timing_arms"]
                }
                measurements = {arm: row.get("measurement") or {} for arm, row in rows.items()}
                if not all(m.get("clock_contract_satisfied") is True for m in measurements.values()):
                    excluded.append(seed)
                    continue
                values = {arm: measurements[arm].get(outcome) for arm in measurements}
                if any(value is None or not math.isfinite(float(value)) for value in values.values()):
                    excluded.append(seed)
                    continue
                native = float(values["native"])
                periodic = float(values["periodic"])
                gap_mean = statistics.fmean(
                    [
                        float(values["gap_permutation_r1"]),
                        float(values["gap_permutation_r2"]),
                    ]
                )
                np_values.append(native - periodic)
                nr_values.append(native - gap_mean)
            digest = hashlib.sha256(f"{master_seed}|{load}|{outcome}".encode()).digest()
            local_seed = int.from_bytes(digest[:8], "big")
            load_result[outcome] = {
                "native_minus_periodic": _bootstrap(
                    np_values, resamples=resamples, seed=local_seed
                ),
                "native_minus_gap_controls": _bootstrap(
                    nr_values, resamples=resamples, seed=local_seed ^ 0x5A5A5A5A
                ),
                "excluded_source_seeds": excluded,
                "interpretation": "positive means native timing is worse because lower is better",
            }
        result["principal_contrasts"][load] = load_result
    _write_json(destination, result)
    _mark(campaign_root, phase="analysis", complete=True)
    return result


def _archive_if_requested(
    campaign_root: Path,
    args: argparse.Namespace,
) -> None:
    if not args.archive_s3:
        return
    campaign = _read_json(campaign_root / "campaign.json")
    if campaign.get("status") != "complete":
        raise RuntimeError("S3 archival is allowed only after the Experiment-2 campaign is complete")
    for name in ("archive_alias", "archive_bucket", "archive_prefix"):
        if not getattr(args, name):
            raise ValueError(f"--archive-s3 requires --{name.replace('_', '-')}")
    result = archive_directory(
        campaign_root,
        settings={
            "enabled": True,
            "backend": "s3",
            "alias": args.archive_alias,
            "bucket": args.archive_bucket,
            "prefix": args.archive_prefix,
            "remote_verify": True,
        },
        experiment="ex2",
        campaign_id=campaign["campaign_id"],
        archive_kind="complete-campaign",
        archive_id=campaign["campaign_id"],
        phase="analysis",
        source_revision=campaign["source_revision"],
        remote_suffix="result",
    )
    print(f"S3 archive verified: {result['destination']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-root", type=Path, required=True)
    parser.add_argument("--transport", choices=("r2lab", "rfsim"), default="r2lab")
    parser.add_argument("--transport-config", type=Path, required=True)
    parser.add_argument("--campaign-root", type=Path)
    parser.add_argument("--session", default="1", help="1, 2, 3, or all")
    parser.add_argument(
        "--phase",
        choices=("qualification", "calibration", "confirmation", "analysis", "all"),
        default="all",
    )
    parser.add_argument("--clock-uncertainty-seconds", type=float, required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--archive-s3", action="store_true")
    parser.add_argument("--archive-alias")
    parser.add_argument("--archive-bucket")
    parser.add_argument("--archive-prefix")
    args = parser.parse_args()

    if not math.isfinite(args.clock_uncertainty_seconds) or args.clock_uncertainty_seconds < 0:
        parser.error("--clock-uncertainty-seconds must be finite and nonnegative")

    plan = _read_json(args.plan.resolve())
    prepared_root = args.prepared_root.expanduser().resolve()
    base_config = args.transport_config.expanduser().resolve()
    prepared_index = _read_json(prepared_root / "prepared-index.json")
    if prepared_index.get("status") != "complete":
        raise RuntimeError("prepared Experiment-2 cohort is incomplete")
    if prepared_index.get("transport_profile") != args.transport:
        raise RuntimeError("prepared cohort transport profile differs from --transport")
    campaign_root = _campaign_root(
        plan,
        prepared_root,
        args.transport,
        args.campaign_root,
    )
    print(f"Campaign          {campaign_root.name}")
    print(f"Results           {campaign_root.relative_to(ROOT)}")

    phases = (
        ["qualification", "calibration", "confirmation", "analysis"]
        if args.phase == "all"
        else [args.phase]
    )

    if "qualification" in phases:
        _qualification(
            campaign_root,
            base_config,
            prepared_root,
            plan,
            args.clock_uncertainty_seconds,
        )
        _mark(campaign_root, phase="qualification")
        print("Qualification     PASSED")

    calibration = None
    if "calibration" in phases or "confirmation" in phases:
        qualification = campaign_root / "qualification/summary.json"
        if not qualification.is_file():
            raise RuntimeError("formal load calibration requires completed qualification")
        calibration = _calibrate(campaign_root, base_config, plan, args.transport)
        _mark(campaign_root, phase="calibration")
        print(
            "Load levels       "
            + ", ".join(
                f"{key}={value:g}Mbps"
                for key, value in calibration["selected_mbps"].items()
            )
        )

    if "confirmation" in phases:
        assert calibration is not None
        sessions = (
            list(range(1, int(plan["confirmation"]["sessions"]) + 1))
            if args.session == "all"
            else [int(args.session)]
        )
        for session in sessions:
            print(f"Confirmation      session {session}")
            _confirmation_session(
                campaign_root,
                base_config,
                prepared_root,
                plan,
                args.transport,
                calibration,
                session=session,
                clock_uncertainty=args.clock_uncertainty_seconds,
            )
        if len(_read_json(campaign_root / "campaign.json")["completed_sessions"]) == int(
            plan["confirmation"]["sessions"]
        ):
            _mark(campaign_root, phase="confirmation")

    if "analysis" in phases:
        campaign = _read_json(campaign_root / "campaign.json")
        if len(campaign["completed_sessions"]) == int(plan["confirmation"]["sessions"]):
            result = _analysis(campaign_root, plan)
            print(f"Analysis          {result['runs_analyzed']} replays")
        elif args.phase == "analysis":
            raise RuntimeError("analysis requires all confirmation sessions")
        else:
            print("Analysis          deferred until all confirmation sessions are complete")

    _archive_if_requested(campaign_root, args)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Experiment-2 error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
