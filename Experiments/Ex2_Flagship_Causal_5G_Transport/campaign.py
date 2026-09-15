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
        retained = _read_json(destination)
        if retained.get("status") == "selected":
            return retained
        raise RuntimeError(
            "Experiment-2 calibration already retained a non-selected result "
            f"({retained.get('status', 'unknown')}); preserve that evidence and start "
            "qualification/full execution under a revised scientific design"
        )

    competitor, broker, route = _transport_context(environment)
    config = manifest["study"]["transport_calibration"]
    rates = [float(value) for value in config["offered_payload_mbps_grid"]]
    repeats = int(config["repeats_per_rate"])
    threshold = float(config["delivery_threshold"])
    seconds = float(config["probe_duration_seconds"])
    packet_bytes = int(config["packet_bytes"])
    base_port = int(config["base_port"])
    achieved_min = float(config["achieved_rate_fraction_min"])
    achieved_max = float(config["achieved_rate_fraction_max"])
    allowed_sender_errors = int(config.get("sender_errors_allowed", 0))

    if not (0 < achieved_min <= 1 <= achieved_max):
        raise ValueError("invalid calibration achieved-rate validity bounds")
    if repeats < 1 or not rates:
        raise ValueError("calibration requires at least one rate and one repeat")

    probes: list[dict[str, Any]] = []
    rate_summaries: list[dict[str, Any]] = []
    crossing: int | None = None

    def retained_result(status: str, *, selected: dict[str, float] | None = None, failure: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": 2,
            "status": status,
            "deployment_hash": environment["deployment_hash"],
            "selection_rule": config["selection_rule"],
            "delivery_threshold": threshold,
            "generator_validity": {
                "achieved_rate_fraction_min": achieved_min,
                "achieved_rate_fraction_max": achieved_max,
                "sender_errors_allowed": allowed_sender_errors,
                "all_repeats_at_rate_must_be_valid": True,
            },
            "route_evidence": route,
            "broker_address": broker,
            "tested_rate_grid_mbps": rates,
            "selected_mbps": selected,
            "rate_summaries": rate_summaries,
            "rate_medians": [
                {
                    "rate_mbps": row["rate_mbps"],
                    "median_delivery_ratio": row["median_delivery_ratio"],
                }
                for row in rate_summaries
            ],
            "probes": probes,
        }
        if failure:
            result["failure"] = failure
        _write_json(destination, result)
        return result

    for rate_index, rate in enumerate(rates):
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError("calibration rates must be finite and positive")
        current: list[dict[str, Any]] = []
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
            sender = probe.get("sender") or {}
            reasons: list[str] = []
            try:
                reported_requested = float(sender["requested_payload_mbps"])
            except (KeyError, TypeError, ValueError):
                reported_requested = math.nan
                reasons.append("sender requested rate unavailable")
            try:
                actual = float(sender["actual_payload_mbps"])
            except (KeyError, TypeError, ValueError):
                actual = math.nan
                reasons.append("sender achieved rate unavailable")
            try:
                sender_errors = int(sender["send_errors"])
            except (KeyError, TypeError, ValueError):
                sender_errors = -1
                reasons.append("sender error count unavailable")

            if math.isfinite(reported_requested) and not math.isclose(
                reported_requested, rate, rel_tol=1e-9, abs_tol=1e-9
            ):
                reasons.append("sender requested rate differs from calibration rate")
            achieved_fraction = actual / rate if math.isfinite(actual) else math.nan
            if math.isfinite(achieved_fraction):
                if achieved_fraction < achieved_min or achieved_fraction > achieved_max:
                    reasons.append(
                        "achieved payload rate outside prespecified validity interval"
                    )
            elif "sender achieved rate unavailable" not in reasons:
                reasons.append("sender achieved rate is not finite")
            if sender_errors >= 0 and sender_errors > allowed_sender_errors:
                reasons.append("sender reported transmission errors")

            valid = not reasons
            probe.update(
                {
                    "rate_mbps": rate,
                    "requested_rate_mbps": rate,
                    "reported_requested_rate_mbps": reported_requested,
                    "actual_payload_mbps": actual,
                    "achieved_rate_fraction": achieved_fraction,
                    "sender_errors": sender_errors,
                    "generator_valid": valid,
                    "generator_invalid_reasons": reasons,
                    "repeat": repeat + 1,
                    "port": port,
                }
            )
            probes.append(probe)
            current.append(probe)
            validity = "valid" if valid else "INVALID"
            actual_text = f"{actual:.3f}" if math.isfinite(actual) else "unavailable"
            print(
                f"Calibration {rate:g} Mbps repeat {repeat + 1}/{repeats}: "
                f"actual={actual_text} Mbps delivery={probe['delivery_ratio']:.6f} {validity}",
                flush=True,
            )

        valid_probes = [probe for probe in current if probe["generator_valid"]]
        delivery_median = (
            statistics.median(float(probe["delivery_ratio"]) for probe in valid_probes)
            if valid_probes
            else None
        )
        actual_median = (
            statistics.median(float(probe["actual_payload_mbps"]) for probe in valid_probes)
            if valid_probes
            else None
        )
        achieved_median = (
            statistics.median(float(probe["achieved_rate_fraction"]) for probe in valid_probes)
            if valid_probes
            else None
        )
        rate_summaries.append(
            {
                "rate_mbps": rate,
                "repeats_expected": repeats,
                "repeats_valid": len(valid_probes),
                "median_actual_payload_mbps": actual_median,
                "median_achieved_rate_fraction": achieved_median,
                "median_delivery_ratio": delivery_median,
            }
        )

        if len(valid_probes) != repeats:
            retained_result(
                "invalid_generator",
                failure=(
                    f"offered-load generator validity failed at {rate:g} Mbps; "
                    "confirmation is blocked and all completed calibration probes were retained"
                ),
            )
            raise RuntimeError(
                f"formal load calibration stopped at {rate:g} Mbps because one or more "
                "repeats did not achieve the prespecified sender-rate contract; evidence retained"
            )

        if delivery_median is not None and delivery_median < threshold:
            crossing = len(rate_summaries) - 1
            break

    if crossing is None:
        retained_result(
            "unbracketed",
            failure=(
                f"no tested rate crossed the median UDP delivery threshold {threshold:.6f}; "
                "the result characterizes only the tested end-to-end loss range"
            ),
        )
        raise RuntimeError(
            "formal load calibration remained unbracketed; preserve load-selection.json "
            "and revise the scientific design before confirmation"
        )

    if crossing < 2:
        retained_result(
            "insufficient_predecessors",
            failure=(
                "the first delivery-threshold crossing did not have two lower valid "
                "grid points required for BELOW and NEAR"
            ),
        )
        raise RuntimeError(
            "formal load calibration crossed too early to select below/near/above; "
            "evidence retained"
        )

    selected = {
        "below": float(rate_summaries[crossing - 2]["rate_mbps"]),
        "near": float(rate_summaries[crossing - 1]["rate_mbps"]),
        "above": float(rate_summaries[crossing]["rate_mbps"]),
    }
    return retained_result("selected", selected=selected)


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
