"""Internal Experiment-2 phase implementation; invoked only by experiment.sh control."""
from __future__ import annotations
import hashlib, math, random, statistics, time
from pathlib import Path
from typing import Any
import yaml
from synthran.experiment_environment import reservation_remaining_seconds
from synthran.workload.bundle import canonical, validate_bundle
from . import source as source_cohort
from .common import _read_json, _write_json, _sha256, _prepared, _deployment_roles
from .runtime import _base_testbed_config, _bundle, _clock_evidence, _victim_run, _prepared_seeds
from .traffic import _broker_address, _stage_udp_tools, _prove_competitor_route, _udp_probe, _start_background, _finish_background

def prepare(_root: Path | None = None, *, manifest: dict[str, Any] | None = None, environment: dict[str, Any] | None = None) -> dict[str, Any]:
    del manifest, environment
    return source_cohort.prepare_latest()

def qualification(root: Path, *, manifest: dict[str, Any], environment: dict[str, Any]) -> dict[str, Any]:
    destination = root / "qualification/summary.json"
    if destination.is_file():
        return _read_json(destination)
    _base_testbed_config(root, environment)
    seed = _prepared_seeds()[0]
    clock = _clock_evidence(root, environment, "qualification")
    summary = _victim_run(
        root,
        environment,
        manifest,
        _bundle(root, environment, seed, "native"),
        root / "qualification/native-no-load",
        clock_uncertainty=float(clock["clock_uncertainty_seconds"]),
    )
    coverage = summary.get("experimental_coverage", {})
    if coverage.get("transport_loss_observed") is not False:
        raise RuntimeError("Experiment-2 no-load qualification observed transport loss")
    workload, competitor = _deployment_roles(environment)
    result = {
        "schema_version": 1,
        "status": "passed",
        "source_seed": seed,
        "deployment_hash": environment["deployment_hash"],
        "roles": {
            "workload_ue": workload.get("device"),
            "competing_ue": competitor.get("device"),
        },
        "clock": clock,
        "measurement": summary.get("measurement"),
        "five_g": summary.get("five_g"),
        "experimental_coverage": coverage,
    }
    _write_json(destination, result)
    return result


def _transport_context(environment: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    _, competitor = _deployment_roles(environment)
    broker = _broker_address(environment)
    _stage_udp_tools(environment, competitor)
    route = _prove_competitor_route(environment, competitor, broker)
    return competitor, broker, route


def calibration(root: Path, *, manifest: dict[str, Any], environment: dict[str, Any]) -> dict[str, Any]:
    destination = root / "calibration/load-selection.json"
    if destination.is_file():
        return _read_json(destination)
    competitor, broker, route = _transport_context(environment)
    config = manifest["study"]["transport_calibration"]
    rates = [float(value) for value in config["offered_payload_mbps_grid"]]
    repeats = int(config["repeats_per_rate"])
    threshold = float(config["delivery_threshold"])
    seconds = float(config["probe_duration_seconds"])
    packet_bytes = int(config["packet_bytes"])
    base_port = int(config["base_port"])
    probes, medians = [], []
    for rate_index, rate in enumerate(rates):
        ratios = []
        for repeat in range(repeats):
            port = base_port + rate_index * repeats + repeat
            probe = _udp_probe(
                environment,
                competitor,
                broker,
                rate=rate,
                seconds=seconds,
                packet_bytes=packet_bytes,
                port=port,
            )
            probe.update({"rate_mbps": rate, "repeat": repeat + 1, "port": port})
            probes.append(probe)
            ratios.append(float(probe["delivery_ratio"]))
            print(
                f"Calibration {rate:g} Mbps repeat {repeat + 1}/{repeats}: delivery={probe['delivery_ratio']:.6f}",
                flush=True,
            )
        medians.append(statistics.median(ratios))
    crossing = next((index for index, value in enumerate(medians) if value < threshold), None)
    if crossing is None or crossing < 2:
        raise RuntimeError(
            "formal load calibration could not select below/near/above by the frozen rule; "
            "preserve the calibration result and revise the design before confirmation"
        )
    selected = {
        "below": rates[crossing - 2],
        "near": rates[crossing - 1],
        "above": rates[crossing],
    }
    result = {
        "schema_version": 1,
        "status": "selected",
        "deployment_hash": environment["deployment_hash"],
        "selection_rule": config["selection_rule"],
        "delivery_threshold": threshold,
        "route_evidence": route,
        "broker_address": broker,
        "selected_mbps": selected,
        "rate_medians": [
            {"rate_mbps": rate, "median_delivery_ratio": median}
            for rate, median in zip(rates, medians)
        ],
        "probes": probes,
    }
    _write_json(destination, result)
    return result


def freeze(root: Path, *, manifest: dict[str, Any], environment: dict[str, Any]) -> dict[str, Any]:
    destination = root / "frozen-design.json"
    if destination.is_file():
        value = _read_json(destination)
        digest = value.pop("design_sha256", None)
        if digest != hashlib.sha256(canonical(value)).hexdigest():
            raise RuntimeError("Experiment-2 frozen design failed its integrity check")
        value["design_sha256"] = digest
        return value
    prepared_root, prepared = _prepared()
    calibration_result = _read_json(root / "calibration/load-selection.json")
    seeds = _prepared_seeds()
    confirmation = manifest["study"]["confirmation"]
    design = {
        "schema_version": 1,
        "experiment": "ex2",
        "campaign_id": root.name,
        "deployment_hash": environment["deployment_hash"],
        "prepared_source": str(prepared_root.relative_to(ROOT)),
        "prepared_index_sha256": _sha256(prepared_root / "prepared-index.json"),
        "upstream_campaign_id": prepared["upstream_campaign_id"],
        "upstream_frozen_design_sha256": prepared["upstream_frozen_design_sha256"],
        "condition": prepared["condition"],
        "source_seeds": seeds,
        "timing_arms": list(source_cohort.ARMS),
        "load_levels_mbps": calibration_result["selected_mbps"],
        "sessions": int(confirmation["sessions"]),
        "seeds_per_session": int(confirmation["seeds_per_session"]),
        "within_block_order_seed": int(confirmation["within_block_order_seed"]),
        "sentinel_every_replays": int(confirmation["sentinel_every_replays"]),
        "expected_replays": len(seeds) * len(source_cohort.ARMS) * 3,
        "roles": _read_json(root / "control/deployment.json")["roles"],
    }
    design["design_sha256"] = hashlib.sha256(canonical(design)).hexdigest()
    _write_json(destination, design)
    return {"status": "complete", **design}


def _frozen(root: Path, environment: dict[str, Any]) -> dict[str, Any]:
    value = _read_json(root / "frozen-design.json")
    digest = value.pop("design_sha256", None)
    observed = hashlib.sha256(canonical(value)).hexdigest()
    value["design_sha256"] = digest
    if digest != observed:
        raise RuntimeError("Experiment-2 frozen design failed its integrity check")
    if value.get("deployment_hash") != environment.get("deployment_hash"):
        raise RuntimeError(
            "current accepted deployment differs from this frozen Experiment-2 campaign; "
            "start a new Experiment-2 campaign instead of mixing testbeds"
        )
    prepared_root, _ = _prepared()
    if _sha256(prepared_root / "prepared-index.json") != value.get("prepared_index_sha256"):
        raise RuntimeError("prepared Experiment-2 source changed after the design freeze")
    return value


def _session_seeds(seeds: list[int], sessions: int, per_session: int, session: int) -> list[int]:
    if len(seeds) != sessions * per_session:
        raise RuntimeError("source-seed count does not match the frozen session design")
    return seeds[(session - 1) * per_session : session * per_session]


def _blocks(seeds: list[int], loads: list[str], *, campaign_id: str, session: int, order_seed: int) -> list[tuple[int, str, list[str]]]:
    blocks = [(seed, load) for seed in seeds for load in loads]
    master = hashlib.sha256(f"{campaign_id}|{session}|{order_seed}".encode()).digest()
    random.Random(int.from_bytes(master[:8], "big")).shuffle(blocks)
    result = []
    for seed, load in blocks:
        arms = list(source_cohort.ARMS)
        digest = hashlib.sha256(
            f"{campaign_id}|{session}|{seed}|{load}|{order_seed}".encode()
        ).digest()
        random.Random(int.from_bytes(digest[:8], "big")).shuffle(arms)
        result.append((seed, load, arms))
    return result


def _background_seconds(bundle: Path) -> float:
    manifest = validate_bundle(bundle)
    scenario = yaml.safe_load((bundle / "resolved-scenario.yml").read_text(encoding="utf-8")) or {}
    mqtt = scenario.get("mqtt", {})
    return (
        float(manifest["duration_seconds"])
        + float(mqtt.get("start_delay_seconds", 30))
        + float(mqtt.get("drain_seconds", 60))
        + 30.0
    )


def _sentinel(root: Path, manifest: dict[str, Any], environment: dict[str, Any], calibration_result: dict[str, Any], competitor: dict[str, Any], broker: str, *, session: int, ordinal: int) -> None:
    config = manifest["study"]["transport_calibration"]
    confirmation = manifest["study"]["confirmation"]
    near = float(calibration_result["selected_mbps"]["near"])
    near_median = next(
        float(row["median_delivery_ratio"])
        for row in calibration_result["rate_medians"]
        if math.isclose(float(row["rate_mbps"]), near)
    )
    minimum = near_median * float(confirmation["sentinel_min_fraction_of_calibrated_near_delivery"])
    port = int(confirmation["sentinel_base_port"]) + session * 100 + ordinal
    probe = _udp_probe(
        environment,
        competitor,
        broker,
        rate=near,
        seconds=float(config["probe_duration_seconds"]),
        packet_bytes=int(config["packet_bytes"]),
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
    _write_json(root / "sentinels" / f"session{session}-after{ordinal:03d}.json", record)
    if float(probe["delivery_ratio"]) < minimum:
        raise RuntimeError("drift sentinel failed; preserve the affected block and diagnose before continuing")


def confirmation(root: Path, *, manifest: dict[str, Any], environment: dict[str, Any]) -> dict[str, Any]:
    frozen = _frozen(root, environment)
    calibration_result = _read_json(root / "calibration/load-selection.json")
    confirmation_plan = manifest["study"]["confirmation"]
    sessions = int(frozen["sessions"])
    per_session = int(frozen["seeds_per_session"])
    loads = ["below", "near", "above"]
    competitor, broker, route = _transport_context(environment)
    packet_bytes = int(manifest["study"]["transport_calibration"]["packet_bytes"])
    safety = float(confirmation_plan["reservation_safety_seconds"])
    completed_before = len(list((root / "runs").glob("*/run-record.json"))) if (root / "runs").is_dir() else 0

    for session in range(1, sessions + 1):
        seeds = _session_seeds(frozen["source_seeds"], sessions, per_session, session)
        blocks = _blocks(
            seeds,
            loads,
            campaign_id=root.name,
            session=session,
            order_seed=int(frozen["within_block_order_seed"]),
        )
        session_root = root / f"sessions/session{session}"
        if not (session_root / "execution-plan.json").is_file():
            flattened = []
            ordinal = 0
            for seed, load, arms in blocks:
                for arm in arms:
                    ordinal += 1
                    flattened.append({"ordinal": ordinal, "seed": seed, "load": load, "arm": arm})
            _write_json(
                session_root / "execution-plan.json",
                {"schema_version": 1, "session": session, "source_seeds": seeds, "order": flattened},
            )
        if (session_root / "summary.json").is_file():
            continue

        clock = _clock_evidence(root, environment, f"session{session}")
        _write_json(
            session_root / "transport-context.json",
            {
                "deployment_hash": environment["deployment_hash"],
                "route_evidence": route,
                "broker_address": broker,
                "competing_ue": competitor,
                "clock": clock,
            },
        )
        replay_base_port = int(confirmation_plan["base_port"]) + (session - 1) * 1000
        ordinal = 0
        for seed, load, arms in blocks:
            block_entries = []
            for arm in arms:
                ordinal += 1
                name = f"s{session}-r{ordinal:03d}-seed{seed:05d}-{load}-{arm}"
                block_entries.append((ordinal, name, arm))
            missing = [entry for entry in block_entries if not (root / "runs" / entry[1] / "run-record.json").is_file()]
            if not missing:
                continue

            representative = _bundle(root, environment, seed, missing[0][2])
            estimated = len(missing) * _background_seconds(representative) + safety
            remaining = reservation_remaining_seconds(environment)
            if remaining is not None and remaining < estimated:
                total = len(list((root / "runs").glob("*/run-record.json"))) if (root / "runs").is_dir() else 0
                print(
                    f"Reservation has {remaining/60:.1f} min remaining; next matched block needs about {estimated/60:.1f} min. "
                    "Pausing before the block.",
                    flush=True,
                )
                return {"status": "paused", "runs_complete": total, "runs_expected": int(frozen["expected_replays"])}

            rate = float(frozen["load_levels_mbps"][load])
            for replay_ordinal, name, arm in missing:
                run_dir = root / "runs" / name
                bundle = _bundle(root, environment, seed, arm)
                seconds = _background_seconds(bundle)
                port = replay_base_port + replay_ordinal
                sender, receiver = _start_background(
                    environment,
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
                        root,
                        environment,
                        manifest,
                        bundle,
                        run_dir,
                        clock_uncertainty=float(clock["clock_uncertainty_seconds"]),
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
                    "ordinal": replay_ordinal,
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
                _write_json(run_dir / "run-record.json", record)
                print(
                    f"[{replay_ordinal}/120] {name} ✓ bg_delivery={background['delivery_ratio']:.5f}",
                    flush=True,
                )
                if (
                    replay_ordinal % int(frozen["sentinel_every_replays"]) == 0
                    and replay_ordinal < 120
                ):
                    _sentinel(
                        root,
                        manifest,
                        environment,
                        calibration_result,
                        competitor,
                        broker,
                        session=session,
                        ordinal=replay_ordinal,
                    )

        records = list(root.glob(f"runs/s{session}-r*-*/run-record.json"))
        if len(records) != 120:
            raise RuntimeError(f"session {session} has {len(records)}/120 completed replays")
        _write_json(
            session_root / "summary.json",
            {"schema_version": 1, "status": "complete", "session": session, "replays": 120},
        )

    records = list((root / "runs").glob("*/run-record.json"))
    expected = int(frozen["expected_replays"])
    if len(records) != expected:
        return {"status": "paused", "runs_complete": len(records), "runs_expected": expected}
    return {
        "status": "complete",
        "runs_complete": len(records),
        "runs_expected": expected,
        "new_runs": len(records) - completed_before,
    }
