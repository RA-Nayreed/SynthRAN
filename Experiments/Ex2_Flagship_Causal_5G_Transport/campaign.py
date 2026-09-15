"""Internal Experiment-2 phase implementation; invoked only by experiment.sh control."""
from __future__ import annotations
import hashlib, json, math, random, statistics, uuid
from pathlib import Path
from typing import Any
import yaml
from synthran.experiment_environment import reservation_remaining_seconds
from synthran.workload.bundle import canonical, validate_bundle
from . import source as source_cohort
from .telemetry import capture_transport_snapshot
from .common import ROOT, _read_json, _write_json, _sha256, _prepared, _deployment_roles
from .runtime import _base_testbed_config, _bundle, _clock_evidence, _prepare_victim_run, _victim_run, _prepared_seeds
from .traffic import ProbeError, _broker_address, _stage_udp_tools, _prove_competitor_route, _udp_probe, _start_background, _finish_background, _probe_quality, _stop_background

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


def _transport_context(environment: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, str]]:
    workload, competitor = _deployment_roles(environment)
    broker = _broker_address(environment)
    _stage_udp_tools(environment, competitor)
    routes = {
        "workload_ue": _prove_competitor_route(environment, workload, broker),
        "competing_ue": _prove_competitor_route(environment, competitor, broker),
    }
    return competitor, broker, routes


def _selected_calibration(root: Path, manifest: dict[str, Any], environment: dict[str, Any]) -> dict[str, Any]:
    destination = root / "calibration/load-selection.json"
    result = _read_json(destination)
    if result.get("status") != "selected":
        raise RuntimeError(
            f"calibration is {result.get('status', 'invalid')}; evidence retained at {destination}. "
            "Review the retained pilot, revise the design, and requalify into a new campaign; "
            "this campaign cannot freeze or confirm."
        )
    if result.get("deployment_hash") != environment["deployment_hash"]:
        raise RuntimeError("calibration belongs to another accepted deployment")
    if result.get("calibration_config_sha256") != hashlib.sha256(
        canonical(manifest["study"]["transport_calibration"])
    ).hexdigest():
        raise RuntimeError("calibration design changed; start a new campaign")
    # A cached status label alone is not sufficient evidence of a valid pilot.
    config = manifest["study"]["transport_calibration"]
    rates = [float(value) for value in config["offered_payload_mbps_grid"]]
    repeats = int(config["repeats_per_rate"])
    rows, probes = result.get("rate_medians", []), result.get("probes", [])
    if result.get("schema_version") != 2 or not 3 <= len(rows) <= len(rates) or len(probes) != len(rows) * repeats:
        raise RuntimeError("calibration selection has incomplete probe evidence; start a new campaign")
    for index, row in enumerate(rows):
        rate = rates[index]
        batch = probes[index * repeats : (index + 1) * repeats]
        if any(
            probe.get("rate_mbps") != rate or probe.get("repeat") != repeat + 1
            or not _probe_quality(probe, config, rate=rate)["valid"]
            for repeat, probe in enumerate(batch)
        ):
            raise RuntimeError("calibration selection contains invalid probe evidence; start a new campaign")
        median = statistics.median(float(probe["delivery_ratio"]) for probe in batch)
        if row.get("rate_mbps") != rate or row.get("median_delivery_ratio") != median or (
            (median < float(config["delivery_threshold"])) != (index == len(rows) - 1)
        ):
            raise RuntimeError("calibration selection does not follow the frozen first-crossing rule")
    selected = dict(zip(("below", "near", "above"), rates[len(rows) - 3 : len(rows)]))
    if result.get("selected_mbps") != selected:
        raise RuntimeError("calibration selected levels do not match the observed first crossing")
    return result


def _calibration(root: Path, *, manifest: dict[str, Any], environment: dict[str, Any]) -> dict[str, Any]:
    destination = root / "calibration/load-selection.json"
    if destination.is_file():
        return _selected_calibration(root, manifest, environment)
    config = manifest["study"]["transport_calibration"]
    rates = [float(value) for value in config["offered_payload_mbps_grid"]]
    repeats = int(config["repeats_per_rate"])
    threshold = float(config["delivery_threshold"])
    seconds = float(config["probe_duration_seconds"])
    packet_bytes = int(config["packet_bytes"])
    base_port = int(config["base_port"])
    lower = float(config["achieved_rate_fraction_min"])
    upper = float(config["achieved_rate_fraction_max"])
    if len(rates) < 3 or any(not math.isfinite(rate) or rate <= 0 for rate in rates) or any(
        right <= left for left, right in zip(rates, rates[1:])
    ):
        raise ValueError("calibration requires at least three strictly increasing positive finite rates")
    if repeats < 1 or not 0 < threshold < 1 or not 0 < lower <= 1 <= upper or not math.isfinite(upper):
        raise ValueError("invalid prespecified calibration repeats, threshold, or rate-fidelity bounds")
    if not math.isfinite(seconds) or seconds <= 0 or not 16 <= packet_bytes <= 65507:
        raise ValueError("invalid calibration duration or UDP payload size")
    if not 1 <= base_port <= 65535 or base_port + len(rates) * repeats - 1 > 65535:
        raise ValueError("calibration ports must fit the UDP port range")
    result = {
        "schema_version": 2,
        "status": "running",
        "deployment_hash": environment["deployment_hash"],
        "calibration_config": config,
        "calibration_config_sha256": hashlib.sha256(canonical(config)).hexdigest(),
        "selection_rule": config["selection_rule"],
        "delivery_threshold": threshold,
        "selected_mbps": None,
        "rate_medians": [],
        "probes": [],
    }
    _write_json(destination, result)
    try:
        competitor, broker, route = _transport_context(environment)
    except Exception as error:
        result.update(status="failed", failure_reason="transport_setup_failed", error=str(error))
        _write_json(destination, result)
        raise
    result.update(route_evidence=route, broker_address=broker)
    _write_json(destination, result)
    for rate_index, rate in enumerate(rates):
        ratios = []
        for repeat in range(repeats):
            port = base_port + rate_index * repeats + repeat
            probe = {"rate_mbps": rate, "repeat": repeat + 1, "port": port}
            try:
                probe.update(_udp_probe(
                    environment, competitor, broker, rate=rate, seconds=seconds,
                    packet_bytes=packet_bytes, port=port,
                ))
                probe["quality"] = _probe_quality(probe, config, rate=rate)
            except Exception as error:
                probe.update(status="failed", error=str(error))
                if isinstance(error, ProbeError):
                    probe["failure_evidence"] = error.evidence
                result["probes"].append(probe)
                result.update(status="failed", failure_reason="probe_execution_failed")
                _write_json(destination, result)
                raise RuntimeError(f"calibration probe failed; evidence retained at {destination}") from error
            result["probes"].append(probe)
            if not probe["quality"]["valid"]:
                result.update(status="failed", failure_reason="invalid_generator_or_accounting")
                _write_json(destination, result)
                raise RuntimeError(
                    f"calibration probe invalid: {', '.join(probe['quality']['reasons'])}; "
                    f"evidence retained at {destination}. Start a new campaign after diagnosis."
                )
            ratios.append(float(probe["delivery_ratio"]))
            _write_json(destination, result)
            print(
                f"Calibration {rate:g} Mbps repeat {repeat + 1}/{repeats}: "
                f"actual={probe['sender']['actual_payload_mbps']:.3f} Mbps delivery={probe['delivery_ratio']:.6f}",
                flush=True,
            )
        median = statistics.median(ratios)
        result["rate_medians"].append({"rate_mbps": rate, "median_delivery_ratio": median})
        _write_json(destination, result)
        if median < threshold:
            if rate_index < 2:
                result.update(status="failed", failure_reason="crossing_before_two_lower_rates")
            else:
                result.update(status="selected", selected_mbps={
                    "below": rates[rate_index - 2], "near": rates[rate_index - 1], "above": rate,
                })
            _write_json(destination, result)
            return _selected_calibration(root, manifest, environment)
    result.update(status="failed", failure_reason="no_delivery_threshold_crossing")
    _write_json(destination, result)
    return _selected_calibration(root, manifest, environment)



def calibration(root: Path, *, manifest: dict[str, Any], environment: dict[str, Any]) -> dict[str, Any]:
    if (root / "calibration/load-selection.json").is_file():
        return _selected_calibration(root, manifest, environment)
    before = root / "calibration/telemetry-before.json"
    if not before.is_file():
        _write_json(before, capture_transport_snapshot(environment))
    try:
        return _calibration(root, manifest=manifest, environment=environment)
    finally:
        after = root / "calibration/telemetry-after.json"
        if not after.is_file():
            _write_json(after, capture_transport_snapshot(environment))

def freeze(root: Path, *, manifest: dict[str, Any], environment: dict[str, Any]) -> dict[str, Any]:
    destination = root / "frozen-design.json"
    if destination.is_file():
        return _frozen(root, environment, manifest)
    prepared_root, prepared = _prepared()
    calibration_result = _selected_calibration(root, manifest, environment)
    seeds = _prepared_seeds()
    confirmation = manifest["study"]["confirmation"]
    design = {
        "schema_version": 1,
        "experiment": "ex2",
        "design_version": manifest["design_version"],
        "study": manifest["study"],
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
        "calibration_sha256": _sha256(root / "calibration/load-selection.json"),
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


def _frozen(root: Path, environment: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    value = _read_json(root / "frozen-design.json")
    digest = value.pop("design_sha256", None)
    observed = hashlib.sha256(canonical(value)).hexdigest()
    value["design_sha256"] = digest
    if digest != observed:
        raise RuntimeError("Experiment-2 frozen design failed its integrity check")
    if value.get("experiment") != "ex2" or value.get("campaign_id") != root.name:
        raise RuntimeError("Experiment-2 frozen design belongs to another campaign")
    if manifest is not None and (
        value.get("design_version") != manifest.get("design_version")
        or value.get("study") != manifest.get("study")
    ):
        raise RuntimeError("Experiment-2 study changed after freeze; start a new campaign")
    if _sha256(root / "calibration/load-selection.json") != value.get("calibration_sha256"):
        raise RuntimeError("Experiment-2 calibration changed after freeze")
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


def _background_seconds(bundle: Path, study: dict[str, Any] | None = None) -> float:
    manifest = validate_bundle(bundle)
    scenario = yaml.safe_load((bundle / "resolved-scenario.yml").read_text(encoding="utf-8")) or {}
    mqtt = scenario.get("mqtt", {})
    return (
        float(manifest["duration_seconds"])
        + float(mqtt.get("start_delay_seconds", 30))
        + max(float(mqtt.get("drain_seconds", 60)), float((study or {}).get("measurement", {}).get("deadline_seconds", 0)))
        + 30.0
    )


def _background_coverage(run_dir: Path, background: dict[str, Any], clock: dict[str, Any]) -> dict[str, Any]:
    """Bound successful background sends against the actual publisher schedule.

    Epoch values are compared only after mapping competitor time to publisher
    time. The clock evidence bounds probe times; this check remains conditional
    on those host clocks staying stable through the replay.
    """
    try:
        sessions = [
            row for line in (run_dir / "publisher.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip() and (row := json.loads(line)).get("record_type") == "session"
        ]
        if not sessions:
            raise ValueError("publisher session evidence is missing")
        starts = [float(row["start_epoch_ns"]) / 1e9 for row in sessions]
        ends = [
            start + float(row["horizon_seconds"]) + float(row["drain_seconds"])
            for start, row in zip(starts, sessions)
        ]
        if any(not math.isfinite(value) for value in starts + ends) or any(
            end <= start for start, end in zip(starts, ends)
        ):
            raise ValueError("invalid publisher observation interval")
        lower, upper = [float(value) for value in clock["competitor_minus_publisher_interval_seconds"]]
        first = float(background["sender"]["first_send_epoch_ns"]) / 1e9
        last = float(background["sender"]["last_send_epoch_ns"]) / 1e9
        if any(not math.isfinite(value) for value in (lower, upper, first, last)) or lower > upper or last < first:
            raise ValueError("invalid sender timestamps or cross-host clock bounds")
    except (OSError, KeyError, TypeError, ValueError) as error:
        return {"valid": False, "reason": f"coverage_evidence_invalid: {error}"}
    latest_start, earliest_end = first - lower, last - upper
    valid = latest_start <= min(starts) and earliest_end >= max(ends)
    return {
        "valid": valid,
        "reason": "covered" if valid else "background_does_not_cover_publisher_horizon_and_drain",
        "publisher_start_epoch_seconds": min(starts),
        "publisher_end_including_drain_epoch_seconds": max(ends),
        "latest_background_start_on_publisher_clock_epoch_seconds": latest_start,
        "earliest_background_end_on_publisher_clock_epoch_seconds": earliest_end,
        "competitor_minus_publisher_interval_seconds": [lower, upper],
        "clock_evidence_path": clock.get("evidence_path"),
        "assumption": "host clock offsets remain within the measured bounds throughout the replay",
        "continuity_evidence": {
            "maximum_send_gap_seconds": background["sender"].get("maximum_send_gap_seconds"),
            "maximum_pacing_lag_seconds": background["sender"].get("maximum_pacing_lag_seconds"),
        },
    }


def _archive_incomplete_attempt(root: Path, run_dir: Path) -> None:
    if not run_dir.exists():
        return
    if (run_dir / "run-record.json").is_file():
        raise RuntimeError("refusing to rerun an already completed treatment cell")
    archive = root / "failed-attempts" / run_dir.name / uuid.uuid4().hex
    if not run_dir.resolve().is_relative_to((root / "runs").resolve()) or not archive.resolve().is_relative_to(
        (root / "failed-attempts").resolve()
    ):
        raise RuntimeError("invalid Experiment-2 attempt archive path")
    archive.parent.mkdir(parents=True, exist_ok=True)
    run_dir.rename(archive)


def _confirmation_replay(root: Path, manifest: dict[str, Any], environment: dict[str, Any],
                         competitor: dict[str, Any], broker: str, *, bundle: Path, run_dir: Path,
                         rate: float, seconds: float, packet_bytes: int, port: int) -> dict[str, Any]:
    # A victim summary and background trace form one indivisible physical attempt.
    # Preserve any incomplete attempt before creating fresh execution artifacts.
    _archive_incomplete_attempt(root, run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    sender = receiver = None
    clock = {}
    background = {}
    try:
        clock = _clock_evidence(root, environment, run_dir.name, refresh=True)
        config = _prepare_victim_run(
            root, environment, manifest, bundle, run_dir,
            clock_uncertainty=float(clock["clock_uncertainty_seconds"]),
        )
        sender, receiver = _start_background(
            environment, competitor, broker, rate=rate, seconds=seconds,
            packet_bytes=packet_bytes, port=port,
        )
        summary = _victim_run(
            root, environment, manifest, bundle, run_dir,
            clock_uncertainty=float(clock["clock_uncertainty_seconds"]), prepared_config=config,
        )
        background = _finish_background(sender, receiver, seconds + 30)
        background["quality"] = _probe_quality(background, manifest["study"]["transport_calibration"], rate=rate)
        background["coverage"] = _background_coverage(run_dir, background, clock)
        if not background["quality"]["valid"] or not background["coverage"]["valid"]:
            raise RuntimeError("confirmation background failed achieved-rate, accounting, or exposure-coverage checks")
        return {"summary": summary, "background": background, "clock": clock}
    except BaseException as error:
        evidence = error.evidence if isinstance(error, ProbeError) else {}
        if sender is not None and receiver is not None:
            evidence["cleanup"] = _stop_background(sender, receiver)
        _write_json(run_dir / "failed-attempt.json", {
            "status": "failed", "error": str(error), "clock": clock,
            "background": background, "failure_evidence": evidence,
        })
        raise


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
    path = root / "sentinels" / f"session{session}-after{ordinal:03d}.json"
    record = {
        "status": "running",
        "session": session,
        "after_replay": ordinal,
        "rate_mbps": near,
        "calibrated_near_median_delivery_ratio": near_median,
        "minimum_delivery_ratio": minimum,
    }
    _write_json(path, record)
    try:
        record.update(_udp_probe(
            environment, competitor, broker, rate=near,
            seconds=float(config["probe_duration_seconds"]), packet_bytes=int(config["packet_bytes"]), port=port,
        ))
        record["quality"] = _probe_quality(record, config, rate=near)
        if not record["quality"]["valid"] or float(record["delivery_ratio"]) < minimum:
            raise RuntimeError("drift sentinel failed; preserve the affected block and diagnose before continuing")
        record["status"] = "passed"
    except BaseException as error:
        record.update(status="failed", error=str(error))
        if isinstance(error, ProbeError):
            record["failure_evidence"] = error.evidence
        raise
    finally:
        _write_json(path, record)


def _validate_sentinel_history(root: Path, frozen: dict[str, Any]) -> None:
    """A completed replay cannot stand in for its interrupted drift checkpoint."""
    for path in (root / "sentinels").glob("*.json"):
        if _read_json(path).get("status") != "passed":
            raise RuntimeError(f"unresolved drift sentinel failure retained at {path}; campaign cannot silently resume")
    interval = int(frozen["sentinel_every_replays"])
    session_replays = int(frozen["seeds_per_session"]) * len(frozen["timing_arms"]) * len(frozen["load_levels_mbps"])
    if interval <= 0:
        raise RuntimeError("invalid frozen sentinel interval")
    for path in (root / "runs").glob("*/run-record.json"):
        record = _read_json(path)
        ordinal = int(record["ordinal"])
        if ordinal % interval == 0 and ordinal < session_replays:
            checkpoint = root / "sentinels" / f"session{int(record['session'])}-after{ordinal:03d}.json"
            if not checkpoint.is_file():
                raise RuntimeError(
                    f"missing drift sentinel after completed replay {ordinal}: {checkpoint}; "
                    "preserve this interrupted campaign and diagnose before a revised campaign; "
                    "a later probe cannot recover the missing historical drift evidence"
                )


def confirmation(root: Path, *, manifest: dict[str, Any], environment: dict[str, Any]) -> dict[str, Any]:
    frozen = _frozen(root, environment, manifest)
    _validate_sentinel_history(root, frozen)
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

        _write_json(
            session_root / "transport-context.json",
            {
                "deployment_hash": environment["deployment_hash"],
                "route_evidence": route,
                "broker_address": broker,
                "competing_ue": competitor,
                "bindings": environment.get("bindings", []),
            },
        )
        telemetry_before = session_root / "telemetry-before.json"
        session_records = list(root.glob(f"runs/s{session}-r*-*/run-record.json"))
        if not telemetry_before.is_file():
            _write_json(
                telemetry_before,
                capture_transport_snapshot(environment, broker_address=broker),
            )
        elif session_records:
            resume_path = session_root / f"telemetry-resume-after-{len(session_records):03d}.json"
            if not resume_path.is_file():
                _write_json(
                    resume_path,
                    capture_transport_snapshot(environment, broker_address=broker),
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
            estimated = len(missing) * _background_seconds(representative, manifest["study"]) + safety
            remaining = reservation_remaining_seconds(environment)
            if remaining is not None and remaining < estimated:
                total = len(list((root / "runs").glob("*/run-record.json"))) if (root / "runs").is_dir() else 0
                _write_json(session_root / f"telemetry-pause-after-{total:03d}.json",
                            capture_transport_snapshot(environment, broker_address=broker))
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
                seconds = _background_seconds(bundle, manifest["study"])
                port = replay_base_port + replay_ordinal
                attempt = _confirmation_replay(
                    root, manifest, environment, competitor, broker, bundle=bundle, run_dir=run_dir,
                    rate=rate, seconds=seconds, packet_bytes=packet_bytes, port=port,
                )
                summary, background = attempt["summary"], attempt["background"]
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
                    "clock": attempt["clock"],
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
        _write_json(session_root / "telemetry-after.json",
                    capture_transport_snapshot(environment, broker_address=broker))
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
