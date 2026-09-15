"""Paired Experiment-2 analysis; invoked internally by experiment.sh."""
from __future__ import annotations

import hashlib
import math
import random
import statistics
from pathlib import Path
from typing import Any, Callable

from .common import _read_json, _write_json
from .source import ARMS
from synthran.workload.bundle import canonical


CONTRASTS: dict[str, tuple[tuple[str, ...], Callable[[dict[str, float]], float]]] = {
    "native_minus_periodic": (
        ("native", "periodic"),
        lambda values: values["native"] - values["periodic"],
    ),
    "native_minus_mean_gap_permutation": (
        ("native", "gap_permutation_r1", "gap_permutation_r2"),
        lambda values: values["native"]
        - statistics.fmean(
            [values["gap_permutation_r1"], values["gap_permutation_r2"]]
        ),
    ),
}


def _bootstrap(values: list[float], *, resamples: int, seed: int) -> dict[str, Any]:
    if resamples < 1:
        raise ValueError("bootstrap_resamples must be positive")
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


def _analysis_seed(master_seed: int, campaign_id: str, *parts: str) -> int:
    digest = hashlib.sha256(
        "|".join([str(master_seed), campaign_id, *parts]).encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big")


def _background_treatment_validity(
    row: dict[str, Any], config: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Validate the competing-load treatment actually delivered with a replay."""
    background = row.get("background") or {}
    sender = background.get("sender") or {}
    reasons: list[str] = []
    try:
        requested = float(row["background_rate_mbps"])
    except (KeyError, TypeError, ValueError):
        return False, ["run record has no valid background_rate_mbps"]
    try:
        sender_requested = float(sender["requested_payload_mbps"])
    except (KeyError, TypeError, ValueError):
        sender_requested = math.nan
        reasons.append("background sender requested rate unavailable")
    try:
        actual = float(sender["actual_payload_mbps"])
    except (KeyError, TypeError, ValueError):
        actual = math.nan
        reasons.append("background sender achieved rate unavailable")
    try:
        errors = int(sender["send_errors"])
    except (KeyError, TypeError, ValueError):
        errors = -1
        reasons.append("background sender error count unavailable")

    minimum = float(config["achieved_rate_fraction_min"])
    maximum = float(config["achieved_rate_fraction_max"])
    allowed_errors = int(config.get("sender_errors_allowed", 0))
    if not math.isfinite(requested) or requested <= 0:
        reasons.append("invalid requested background rate")
    expected = config.get("expected_load_levels_mbps", {}).get(row.get("load_level"))
    if expected is not None and requested != float(expected):
        reasons.append("recorded background rate differs from frozen treatment level")
    if not math.isfinite(sender_requested):
        reasons.append("background sender requested rate is not finite")
    if background.get("coverage", {}).get("valid") is not True:
        reasons.append("background exposure coverage unavailable or invalid")
    if math.isfinite(sender_requested) and not math.isclose(
        sender_requested, requested, rel_tol=1e-9, abs_tol=1e-9
    ):
        reasons.append("background sender requested rate differs from frozen load")
    if math.isfinite(actual) and requested > 0:
        fraction = actual / requested
        if fraction < minimum or fraction > maximum:
            reasons.append(
                "background achieved payload rate outside prespecified validity interval"
            )
    elif "background sender achieved rate unavailable" not in reasons:
        reasons.append("background sender achieved rate is not finite")
    if errors < 0 or errors > allowed_errors:
        reasons.append("background sender reported transmission errors")
    return not reasons, reasons


def _finite_measurement(
    row: dict[str, Any],
    outcome: str,
    background_config: dict[str, Any],
) -> tuple[float | None, str | None]:
    treatment_valid, treatment_reasons = _background_treatment_validity(
        row, background_config
    )
    if not treatment_valid:
        return None, "background treatment invalid: " + "; ".join(treatment_reasons)
    measurement = row.get("measurement") or {}
    if not isinstance(measurement, dict):
        return None, "measurement evidence is not an object"
    if measurement.get("clock_contract_satisfied") is not True:
        return None, "clock contract not satisfied"
    raw = measurement.get(outcome)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, f"undefined {outcome}"
    if isinstance(raw, bool) or not math.isfinite(value):
        return None, f"undefined {outcome}"
    return value, None


def _seed_contrast(
    by_key: dict[tuple[int, str, str], dict[str, Any]],
    *,
    seed: int,
    load: str,
    outcome: str,
    contrast: str,
    background_config: dict[str, Any] | None = None,
) -> tuple[float | None, dict[str, Any] | None]:
    try:
        required_arms, compute = CONTRASTS[contrast]
    except KeyError as exc:
        raise ValueError(f"unsupported Experiment-2 contrast: {contrast}") from exc

    missing = [arm for arm in required_arms if (seed, load, arm) not in by_key]
    if missing:
        return None, {
            "seed": seed,
            "reason": "missing treatment cell",
            "arms": missing,
        }

    config = background_config or {
        "achieved_rate_fraction_min": 0.95,
        "achieved_rate_fraction_max": 1.05,
        "sender_errors_allowed": 0,
    }
    values: dict[str, float] = {}
    invalid: dict[str, str] = {}
    for arm in required_arms:
        value, reason = _finite_measurement(by_key[(seed, load, arm)], outcome, config)
        if reason is not None:
            invalid[arm] = reason
        else:
            assert value is not None
            values[arm] = value
    if invalid:
        return None, {
            "seed": seed,
            "reason": "required arm invalid",
            "arms": invalid,
        }

    return float(compute(values)), None


def _contrast_result(
    by_key: dict[tuple[int, str, str], dict[str, Any]],
    *,
    seeds: list[int],
    load: str,
    outcome: str,
    contrast: str,
    background_config: dict[str, Any],
    resamples: int,
    bootstrap_seed: int,
) -> tuple[dict[str, Any], dict[int, float]]:
    required_arms, _ = CONTRASTS[contrast]
    values_by_seed: dict[int, float] = {}
    excluded: list[dict[str, Any]] = []
    for seed in seeds:
        value, exclusion = _seed_contrast(
            by_key,
            seed=seed,
            load=load,
            outcome=outcome,
            contrast=contrast,
            background_config=background_config,
        )
        if exclusion is not None:
            excluded.append(exclusion)
            continue
        assert value is not None
        values_by_seed[seed] = value

    estimate = _bootstrap(
        [values_by_seed[seed] for seed in seeds if seed in values_by_seed],
        resamples=resamples,
        seed=bootstrap_seed,
    )
    estimate.update(
        {
            "included_source_seeds": [seed for seed in seeds if seed in values_by_seed],
            "paired_differences": [{"seed": seed, "difference": values_by_seed[seed]} for seed in seeds if seed in values_by_seed],
            "excluded": excluded,
            "required_arms": list(required_arms),
            "estimand": "paired mean difference across source seeds",
            "direction": "positive means native timing is worse because lower is better",
        }
    )
    return estimate, values_by_seed


def _interaction_result(
    by_key: dict[tuple[int, str, str], dict[str, Any]],
    *,
    seeds: list[int],
    reference_load: str,
    comparison_load: str,
    outcome: str,
    contrast: str,
    background_config: dict[str, Any],
    resamples: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    required_arms, _ = CONTRASTS[contrast]
    differences: dict[int, float] = {}
    excluded: list[dict[str, Any]] = []

    for seed in seeds:
        reference_value, reference_exclusion = _seed_contrast(
            by_key,
            seed=seed,
            load=reference_load,
            outcome=outcome,
            contrast=contrast,
            background_config=background_config,
        )
        comparison_value, comparison_exclusion = _seed_contrast(
            by_key,
            seed=seed,
            load=comparison_load,
            outcome=outcome,
            contrast=contrast,
            background_config=background_config,
        )
        if reference_exclusion is not None or comparison_exclusion is not None:
            reasons: dict[str, Any] = {}
            if reference_exclusion is not None:
                reasons[reference_load] = reference_exclusion
            if comparison_exclusion is not None:
                reasons[comparison_load] = comparison_exclusion
            excluded.append(
                {
                    "seed": seed,
                    "reason": "contrast not estimable at both paired loads",
                    "load_reasons": reasons,
                }
            )
            continue
        assert reference_value is not None and comparison_value is not None
        differences[seed] = comparison_value - reference_value

    estimate = _bootstrap(
        [differences[seed] for seed in seeds if seed in differences],
        resamples=resamples,
        seed=bootstrap_seed,
    )
    estimate.update(
        {
            "included_source_seeds": [seed for seed in seeds if seed in differences],
            "paired_differences": [{"seed": seed, "difference": differences[seed]} for seed in seeds if seed in differences],
            "excluded": excluded,
            "required_arms": list(required_arms),
            "reference_load": reference_load,
            "comparison_load": comparison_load,
            "estimand": (
                "paired difference in the timing contrast across the same source seeds: "
                f"{comparison_load} minus {reference_load}"
            ),
            "direction": (
                "positive means the native-timing penalty is larger at the comparison "
                "load than at the reference load"
            ),
        }
    )
    return estimate


def analysis(root: Path, *, manifest: dict[str, Any], environment: dict[str, Any] | None = None) -> dict[str, Any]:
    # A cached summary must not bypass changed or incomplete source evidence.
    del manifest, environment
    destination = root / "analysis/summary.json"
    frozen = _read_json(root / "frozen-design.json")
    digest = frozen.get("design_sha256")
    payload = {key: value for key, value in frozen.items() if key != "design_sha256"}
    if digest != hashlib.sha256(canonical(payload)).hexdigest():
        raise RuntimeError("Experiment-2 frozen design failed its integrity check")
    if frozen.get("experiment") != "ex2" or frozen.get("campaign_id") != root.name:
        raise RuntimeError("Experiment-2 frozen design belongs to another campaign")
    study = frozen.get("study")
    if not isinstance(study, dict):
        raise RuntimeError("Experiment-2 frozen design has no frozen study; start a new campaign")
    statistics_plan = study["statistics"]
    outcomes = list(statistics_plan["principal_outcomes"])
    loads = list(study["confirmation"]["load_levels"])
    arms = list(frozen["timing_arms"])
    seeds = frozen["source_seeds"]
    if set(arms) != set(ARMS) or len(arms) != len(ARMS):
        raise RuntimeError("Experiment-2 frozen timing arms differ from the supported matched design")
    if (loads != ["below", "near", "above"] or not isinstance(seeds, list) or not seeds
            or any(type(seed) is not int for seed in seeds) or len(seeds) != len(set(seeds))):
        raise RuntimeError("Experiment-2 frozen load levels or source seeds are invalid")
    expected_keys = {(seed, load, arm) for seed in seeds for load in loads for arm in arms}
    if int(frozen["expected_replays"]) != len(expected_keys):
        raise RuntimeError("Experiment-2 expected replay count differs from its frozen treatment matrix")
    by_key = {}
    for path in sorted((root / "runs").glob("*/run-record.json")):
        row = _read_json(path)
        if row.get("status") != "complete":
            raise RuntimeError(f"Experiment-2 analysis found an incomplete replay: {path.parent.name}")
        if (type(row.get("seed")) is not int or not isinstance(row.get("load_level"), str)
                or not isinstance(row.get("timing_arm"), str)):
            raise RuntimeError(f"Experiment-2 replay has invalid treatment identity: {path.parent.name}")
        key = (row["seed"], row["load_level"], row["timing_arm"])
        if key in by_key:
            raise RuntimeError("Experiment-2 confirmation contains duplicate treatment cells")
        by_key[key] = row
    if set(by_key) != expected_keys:
        missing = sorted(expected_keys - set(by_key))
        unexpected = sorted(set(by_key) - expected_keys)
        raise RuntimeError(
            f"Experiment-2 confirmation does not match its frozen treatment matrix; "
            f"missing={missing}; unexpected={unexpected}"
        )
    records = list(by_key.values())
    background_config = {**study["transport_calibration"], "expected_load_levels_mbps": frozen["load_levels_mbps"]}
    resamples = int(statistics_plan["bootstrap_resamples"])
    master_seed = int(statistics_plan["bootstrap_seed"])
    contrast_names = list(statistics_plan.get("principal_contrast_ids", CONTRASTS))
    if set(contrast_names) != set(CONTRASTS):
        raise RuntimeError("Experiment-2 manifest contrast identifiers differ from the implemented frozen analysis")
    missing_arms = sorted(
        {arm for contrast in contrast_names for arm in CONTRASTS[contrast][0]} - set(arms)
    )
    if missing_arms:
        raise RuntimeError(
            "Experiment-2 frozen design is missing analysis arm(s): "
            + ", ".join(missing_arms)
        )

    interaction_plan = statistics_plan.get(
        "load_interactions",
        {
            "near_minus_below": {"comparison": "near", "reference": "below"},
            "above_minus_below": {"comparison": "above", "reference": "below"},
        },
    )
    if not isinstance(interaction_plan, dict) or not interaction_plan:
        raise RuntimeError("Experiment-2 statistics require at least one paired load interaction")

    result: dict[str, Any] = {
        "schema_version": 2,
        "status": "complete",
        "experiment": "ex2",
        "campaign_id": root.name,
        "deployment_hash": frozen["deployment_hash"],
        "frozen_design_sha256": digest,
        "experimental_unit": "source_seed",
        "runs_analyzed": len(records),
        "source_seeds": seeds,
        "load_levels_mbps": frozen["load_levels_mbps"],
        "timing_arms": arms,
        "principal_contrasts": {},
        "load_interactions": {},
        "inference_policy": {
            "bootstrap_resamples": resamples,
            "confidence_intervals": "pointwise percentile 95% bootstrap intervals",
            "multiplicity_adjustment": statistics_plan.get("multiplicity_adjustment", "none"),
            "practical_importance": statistics_plan.get(
                "practical_importance_policy",
                "No equivalence or practical-importance claim without an independently justified margin.",
            ),
            "load_treatment_validity": {
                "achieved_rate_fraction_min": float(background_config["achieved_rate_fraction_min"]),
                "achieved_rate_fraction_max": float(background_config["achieved_rate_fraction_max"]),
                "sender_errors_allowed": int(background_config.get("sender_errors_allowed", 0)),
            },
        },
        "notes": [
            "Each source seed is one independent experimental unit within each load level.",
            "Clock uncertainty is not incorporated into bootstrap intervals; session-level dependence is not modeled.",
            "The two gap permutations are repeated matched controls and do not increase n.",
            "Eligibility is contrast-specific: an invalid gap arm does not discard an otherwise valid native-periodic contrast.",
            "A replay whose competing-load sender violates the frozen achieved-rate/error contract is invalid for contrasts requiring that arm.",
            "Load interactions are paired within the same source seed and require that contrast to be estimable at both loads.",
            "Intervals are pointwise 95% intervals; no familywise claim is implied unless a multiplicity procedure is explicitly frozen.",
        ],
    }

    for load in loads:
        load_result: dict[str, Any] = {}
        for outcome in outcomes:
            outcome_result: dict[str, Any] = {}
            for contrast in contrast_names:
                estimate, _ = _contrast_result(
                    by_key,
                    seeds=seeds,
                    load=load,
                    outcome=outcome,
                    contrast=contrast,
                    background_config=background_config,
                    resamples=resamples,
                    bootstrap_seed=_analysis_seed(
                        master_seed, root.name, "main", load, outcome, contrast
                    ),
                )
                outcome_result[contrast] = estimate
            load_result[outcome] = outcome_result
        result["principal_contrasts"][load] = load_result

    for interaction_id, spec in interaction_plan.items():
        if not isinstance(spec, dict):
            raise RuntimeError(f"invalid Experiment-2 interaction specification: {interaction_id}")
        reference = str(spec.get("reference", ""))
        comparison = str(spec.get("comparison", ""))
        if reference not in loads or comparison not in loads or reference == comparison:
            raise RuntimeError(f"invalid Experiment-2 load interaction: {interaction_id}")
        interaction_result: dict[str, Any] = {}
        for outcome in outcomes:
            outcome_result = {}
            for contrast in contrast_names:
                outcome_result[contrast] = _interaction_result(
                    by_key,
                    seeds=seeds,
                    reference_load=reference,
                    comparison_load=comparison,
                    outcome=outcome,
                    contrast=contrast,
                    background_config=background_config,
                    resamples=resamples,
                    bootstrap_seed=_analysis_seed(
                        master_seed,
                        root.name,
                        "interaction",
                        str(interaction_id),
                        outcome,
                        contrast,
                    ),
                )
            interaction_result[outcome] = outcome_result
        result["load_interactions"][str(interaction_id)] = interaction_result

    _write_json(destination, result)
    return result
