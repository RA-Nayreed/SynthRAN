"""Research experiment contracts, campaign planning, and offline analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import tempfile
from typing import Any, Mapping, Sequence

from synthran.experiment import SENSOR_COUNT, ExperimentError, validate_run_id

RESEARCH_SPEC_SCHEMA = "synthran/research-experiment/v1alpha1"
RESEARCH_CAMPAIGN_SCHEMA = "synthran/research-campaign/v1alpha1"
RESEARCH_SUMMARY_SCHEMA = "synthran/research-summary/v1alpha1"
RESEARCH_SAMPLE_SCHEMA = "synthran/research-sample/v1alpha1"
RESEARCH_RESULT_SCHEMA = "synthran/research-result/v1alpha1"
RESEARCH_EVIDENCE_SCHEMA = "synthran/research-evidence/v1alpha1"
RESEARCH_WINDOW_SCHEMA = "synthran/research-window/v1alpha1"
DEFAULT_SENSOR_PERIOD_SECONDS = 10
DEFAULT_MEASUREMENT_SECONDS = 180
DEFAULT_WARMUP_SECONDS = 15
DEFAULT_SAMPLE_INTERVAL_SECONDS = 1.0
DEFAULT_PAYLOAD_BYTES = 1024


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as stream:
        stream.write(content)
        temporary = Path(stream.name)
    temporary.replace(path)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_text(path, json.dumps(dict(payload), indent=2, sort_keys=True) + "\n")


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExperimentError(f"research artifact is missing: {path.name}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExperimentError(f"research artifact is not readable JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise ExperimentError(f"research artifact must contain one JSON object: {path.name}")
    return value


def _read_jsonl(path: Path) -> list[Mapping[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise ExperimentError(f"research artifact is not readable JSONL: {path.name}") from exc
    records: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ExperimentError(
                f"research JSONL artifact {path.name} has invalid line {line_number}"
            ) from exc
        if not isinstance(value, dict):
            raise ExperimentError(
                f"research JSONL artifact {path.name} line {line_number} is not an object"
            )
        records.append(value)
    return records


def append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()


def _finite_number(value: Any, *, name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExperimentError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ExperimentError(f"{name} must be finite")
    if minimum is not None and number < minimum:
        raise ExperimentError(f"{name} must be at least {minimum}")
    return number


@dataclass(frozen=True)
class LoadProfile:
    mode: str
    target_fraction: float = 0.0
    reference_kbps: float | None = None
    payload_bytes: int = DEFAULT_PAYLOAD_BYTES

    def __post_init__(self) -> None:
        if self.mode not in {"baseline", "congestion", "calibration"}:
            raise ExperimentError("research load mode must be baseline, congestion, or calibration")
        fraction = _finite_number(self.target_fraction, name="target_fraction", minimum=0.0)
        if fraction > 1.0:
            raise ExperimentError("target_fraction must not exceed 1.0")
        if self.mode == "baseline" and fraction != 0.0:
            raise ExperimentError("baseline load must use target_fraction=0")
        if self.mode == "congestion" and not 0.0 < fraction <= 1.0:
            raise ExperimentError("congestion load requires 0 < target_fraction <= 1")
        if self.mode == "calibration" and fraction != 1.0:
            raise ExperimentError("calibration load requires target_fraction=1")
        if self.reference_kbps is not None:
            _finite_number(self.reference_kbps, name="reference_kbps", minimum=1.0)
        if self.mode in {"congestion", "calibration"} and self.reference_kbps is None:
            raise ExperimentError(f"{self.mode} load requires reference_kbps")
        if isinstance(self.payload_bytes, bool) or not isinstance(self.payload_bytes, int):
            raise ExperimentError("payload_bytes must be an integer")
        if not 64 <= self.payload_bytes <= 65536:
            raise ExperimentError("payload_bytes must be between 64 and 65536")

    @property
    def target_kbps(self) -> float:
        if self.mode == "baseline":
            return 0.0
        assert self.reference_kbps is not None
        return self.reference_kbps * self.target_fraction

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "target_fraction": self.target_fraction,
            "reference_kbps": self.reference_kbps,
            "target_kbps": self.target_kbps,
            "payload_bytes": self.payload_bytes,
        }


@dataclass(frozen=True)
class ResearchSpec:
    campaign_id: str
    run_id: str
    network_run_id: str
    condition: str
    cooja_seed: int
    sensor_period_seconds: int = DEFAULT_SENSOR_PERIOD_SECONDS
    warmup_seconds: int = DEFAULT_WARMUP_SECONDS
    measurement_seconds: int = DEFAULT_MEASUREMENT_SECONDS
    sample_interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS
    load: LoadProfile = LoadProfile("baseline")

    def __post_init__(self) -> None:
        validate_run_id(self.campaign_id)
        validate_run_id(self.run_id)
        validate_run_id(self.network_run_id)
        if self.condition not in {"baseline", "congestion", "calibration"}:
            raise ExperimentError("research condition must be baseline, congestion, or calibration")
        if self.condition != self.load.mode:
            raise ExperimentError("research condition and load mode must match")
        if isinstance(self.cooja_seed, bool) or not isinstance(self.cooja_seed, int) or self.cooja_seed < 0:
            raise ExperimentError("cooja_seed must be a non-negative integer")
        if not 1 <= self.sensor_period_seconds <= 3600:
            raise ExperimentError("sensor_period_seconds must be between 1 and 3600")
        if not 0 <= self.warmup_seconds <= 600:
            raise ExperimentError("warmup_seconds must be between 0 and 600")
        if not 30 <= self.measurement_seconds <= 3600:
            raise ExperimentError("measurement_seconds must be between 30 and 3600")
        if self.warmup_seconds + self.measurement_seconds > 3480:
            raise ExperimentError("research warmup and measurement must fit the live collection limit")
        required_events = math.ceil(
            (self.warmup_seconds + self.measurement_seconds) / self.sensor_period_seconds
        ) + 2
        if required_events > 100:
            raise ExperimentError(
                "research window requires more than 100 events per sensor; increase the sensor period or shorten the window"
            )
        interval = _finite_number(
            self.sample_interval_seconds,
            name="sample_interval_seconds",
            minimum=0.2,
        )
        if interval > 60.0:
            raise ExperimentError("sample_interval_seconds must not exceed 60")

    @property
    def minimum_per_sensor(self) -> int:
        total_seconds = self.warmup_seconds + self.measurement_seconds
        return max(3, math.ceil(total_seconds / self.sensor_period_seconds) + 2)

    @property
    def expected_events(self) -> int:
        per_sensor = max(1, math.ceil(self.measurement_seconds / self.sensor_period_seconds))
        return SENSOR_COUNT * per_sensor

    @property
    def collection_timeout_seconds(self) -> int:
        return self.warmup_seconds + self.measurement_seconds + 120

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RESEARCH_SPEC_SCHEMA,
            "campaign_id": self.campaign_id,
            "run_id": self.run_id,
            "network_run_id": self.network_run_id,
            "condition": self.condition,
            "cooja_seed": self.cooja_seed,
            "sensor_count": SENSOR_COUNT,
            "sensor_period_seconds": self.sensor_period_seconds,
            "warmup_seconds": self.warmup_seconds,
            "measurement_seconds": self.measurement_seconds,
            "sample_interval_seconds": self.sample_interval_seconds,
            "minimum_per_sensor": self.minimum_per_sensor,
            "expected_events": self.expected_events,
            "load": self.load.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResearchSpec":
        if value.get("schema") != RESEARCH_SPEC_SCHEMA:
            raise ExperimentError("research spec schema is unsupported")
        load_value = value.get("load")
        if not isinstance(load_value, dict):
            raise ExperimentError("research spec load is malformed")
        reference = load_value.get("reference_kbps")
        return cls(
            campaign_id=str(value.get("campaign_id", "")),
            run_id=str(value.get("run_id", "")),
            network_run_id=str(value.get("network_run_id", "")),
            condition=str(value.get("condition", "")),
            cooja_seed=int(value.get("cooja_seed", -1)),
            sensor_period_seconds=int(value.get("sensor_period_seconds", DEFAULT_SENSOR_PERIOD_SECONDS)),
            warmup_seconds=int(value.get("warmup_seconds", DEFAULT_WARMUP_SECONDS)),
            measurement_seconds=int(value.get("measurement_seconds", DEFAULT_MEASUREMENT_SECONDS)),
            sample_interval_seconds=float(value.get("sample_interval_seconds", DEFAULT_SAMPLE_INTERVAL_SECONDS)),
            load=LoadProfile(
                mode=str(load_value.get("mode", "")),
                target_fraction=float(load_value.get("target_fraction", 0.0)),
                reference_kbps=None if reference is None else float(reference),
                payload_bytes=int(load_value.get("payload_bytes", DEFAULT_PAYLOAD_BYTES)),
            ),
        )


def save_research_spec(spec: ResearchSpec, destination: Path) -> None:
    _atomic_json(destination, spec.to_dict())


def load_research_spec(path: Path) -> ResearchSpec:
    return ResearchSpec.from_dict(_read_json(path))


@dataclass(frozen=True)
class CampaignRun:
    ordinal: int
    seed: int
    condition: str
    target_fraction: float
    run_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "seed": self.seed,
            "condition": self.condition,
            "target_fraction": self.target_fraction,
            "run_id": self.run_id,
        }


@dataclass(frozen=True)
class CampaignPlan:
    campaign_id: str
    network_run_id: str
    randomization_seed: int
    reference_kbps: float
    runs: tuple[CampaignRun, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RESEARCH_CAMPAIGN_SCHEMA,
            "campaign_id": self.campaign_id,
            "network_run_id": self.network_run_id,
            "randomization_seed": self.randomization_seed,
            "reference_kbps": self.reference_kbps,
            "runs": [run.to_dict() for run in self.runs],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignPlan":
        if value.get("schema") != RESEARCH_CAMPAIGN_SCHEMA:
            raise ExperimentError("research campaign schema is unsupported")
        raw_runs = value.get("runs")
        if not isinstance(raw_runs, list) or not raw_runs:
            raise ExperimentError("research campaign runs are malformed")
        runs: list[CampaignRun] = []
        for item in raw_runs:
            if not isinstance(item, dict):
                raise ExperimentError("research campaign contains a malformed run")
            condition = str(item.get("condition", ""))
            fraction = float(item.get("target_fraction", -1.0))
            if condition not in {"baseline", "congestion"}:
                raise ExperimentError("research campaign condition is unsupported")
            if (condition == "baseline" and fraction != 0.0) or (
                condition == "congestion" and not 0.0 < fraction <= 1.0
            ):
                raise ExperimentError("research campaign target fraction is invalid")
            runs.append(
                CampaignRun(
                    ordinal=int(item.get("ordinal", 0)),
                    seed=int(item.get("seed", -1)),
                    condition=condition,
                    target_fraction=fraction,
                    run_id=validate_run_id(str(item.get("run_id", ""))),
                )
            )
        return cls(
            campaign_id=validate_run_id(str(value.get("campaign_id", ""))),
            network_run_id=validate_run_id(str(value.get("network_run_id", ""))),
            randomization_seed=int(value.get("randomization_seed", 0)),
            reference_kbps=_finite_number(
                value.get("reference_kbps"), name="reference_kbps", minimum=1.0
            ),
            runs=tuple(runs),
        )


def build_campaign_plan(
    *,
    campaign_id: str,
    network_run_id: str,
    seeds: Sequence[int],
    congestion_fractions: Sequence[float],
    reference_kbps: float,
    randomization_seed: int,
) -> CampaignPlan:
    validate_run_id(campaign_id)
    validate_run_id(network_run_id)
    if not seeds:
        raise ExperimentError("campaign requires at least one Cooja seed")
    if len(set(seeds)) != len(seeds):
        raise ExperimentError("campaign Cooja seeds must be unique")
    if any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds):
        raise ExperimentError("campaign Cooja seeds must be non-negative integers")
    reference = _finite_number(reference_kbps, name="reference_kbps", minimum=1.0)
    fractions = [float(value) for value in congestion_fractions]
    if any(not math.isfinite(value) or value <= 0.0 or value > 1.0 for value in fractions):
        raise ExperimentError("campaign congestion fractions must be within (0, 1]")
    if len(set(fractions)) != len(fractions):
        raise ExperimentError("campaign congestion fractions must be unique")
    if isinstance(randomization_seed, bool) or not isinstance(randomization_seed, int):
        raise ExperimentError("campaign randomization seed must be an integer")

    rng = random.Random(randomization_seed)
    runs: list[CampaignRun] = []
    ordinal = 1
    for seed in seeds:
        conditions = [("baseline", 0.0)] + [("congestion", value) for value in fractions]
        rng.shuffle(conditions)
        for condition, fraction in conditions:
            suffix = "baseline" if condition == "baseline" else f"c{int(round(fraction * 100)):02d}"
            run_id = validate_run_id(f"{campaign_id}-s{seed}-{suffix}")
            runs.append(CampaignRun(ordinal, seed, condition, fraction, run_id))
            ordinal += 1
    return CampaignPlan(
        campaign_id=campaign_id,
        network_run_id=network_run_id,
        randomization_seed=randomization_seed,
        reference_kbps=reference,
        runs=tuple(runs),
    )


def save_campaign_plan(plan: CampaignPlan, destination: Path) -> None:
    _atomic_json(destination, plan.to_dict())


def load_campaign_plan(path: Path) -> CampaignPlan:
    return CampaignPlan.from_dict(_read_json(path))


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    if not 0.0 <= q <= 1.0:
        raise ExperimentError("percentile quantile must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _utc_seconds(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError) as exc:
        raise ExperimentError("telemetry received_at_utc is invalid") from exc


def telemetry_metrics(records: Sequence[Mapping[str, Any]], *, expected_events: int) -> dict[str, Any]:
    if expected_events < 1:
        raise ExperimentError("expected_events must be positive")
    by_sensor: dict[str, list[Mapping[str, Any]]] = {
        f"sensor-{index:02d}": [] for index in range(1, SENSOR_COUNT + 1)
    }
    for record in records:
        sensor_id = record.get("sensor_id")
        if sensor_id not in by_sensor:
            raise ExperimentError("telemetry contains an unexpected sensor")
        by_sensor[str(sensor_id)].append(record)

    gaps = 0
    inter_arrivals: list[float] = []
    per_sensor_delivery: dict[str, float] = {}
    expected_per_sensor = expected_events / SENSOR_COUNT
    for sensor_id, sensor_records in by_sensor.items():
        ordered = sorted(sensor_records, key=lambda item: int(item.get("sequence", 0)))
        sequences = [int(item.get("sequence", 0)) for item in ordered]
        if sequences:
            gaps += max(0, sequences[-1] - sequences[0] + 1 - len(set(sequences)))
        per_sensor_delivery[sensor_id] = min(1.0, len(ordered) / expected_per_sensor)
        by_receive = sorted(_utc_seconds(str(item.get("received_at_utc", ""))) for item in ordered)
        inter_arrivals.extend(
            later - earlier for earlier, later in zip(by_receive, by_receive[1:]) if later >= earlier
        )

    received = len(records)
    return {
        "received_events": received,
        "expected_events": expected_events,
        "delivery_ratio": min(1.0, received / expected_events),
        "sequence_gap_count": gaps,
        "sequence_gap_rate": gaps / expected_events,
        "per_sensor_delivery_ratio": per_sensor_delivery,
        "inter_arrival_median_ms": None if not inter_arrivals else statistics.median(inter_arrivals) * 1000.0,
        "inter_arrival_p95_ms": None if not inter_arrivals else percentile(inter_arrivals, 0.95) * 1000.0,
    }


def probe_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rtts = [
        float(record["rtt_ms"])
        for record in records
        if record.get("success") is True and isinstance(record.get("rtt_ms"), (int, float))
    ]
    attempts = len(records)
    successes = len(rtts)
    return {
        "probe_attempts": attempts,
        "probe_successes": successes,
        "probe_timeout_rate": 0.0 if attempts == 0 else (attempts - successes) / attempts,
        "rtt_median_ms": None if not rtts else statistics.median(rtts),
        "rtt_p95_ms": percentile(rtts, 0.95),
        "rtt_p99_ms": percentile(rtts, 0.99),
        "rtt_jitter_ms": None if len(rtts) < 2 else statistics.pstdev(rtts),
    }


def network_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(records) < 2:
        return {"ue_tx_kbps": None, "ue_rx_kbps": None, "sample_count": len(records)}
    ordered = sorted(records, key=lambda item: float(item.get("monotonic_seconds", 0.0)))
    first, last = ordered[0], ordered[-1]
    duration = float(last.get("monotonic_seconds", 0.0)) - float(first.get("monotonic_seconds", 0.0))
    if duration <= 0:
        raise ExperimentError("network samples have a non-positive observation interval")

    def rate(field: str) -> float:
        before = int(first.get(field, 0))
        after = int(last.get(field, 0))
        return max(0, after - before) * 8.0 / duration / 1000.0

    return {
        "ue_tx_kbps": rate("ue_tx_bytes"),
        "ue_rx_kbps": rate("ue_rx_bytes"),
        "sample_count": len(records),
    }


def load_metrics(records: Sequence[Mapping[str, Any]], *, target_kbps: float) -> dict[str, Any]:
    values = [
        float(record["measured_kbps"])
        for record in records
        if isinstance(record.get("measured_kbps"), (int, float))
    ]
    actual = None if not values else statistics.median(values)
    return {
        "target_kbps": target_kbps,
        "measured_kbps_median": actual,
        "target_achievement_ratio": None if actual is None or target_kbps <= 0 else actual / target_kbps,
    }


def analyze_research_run(run_directory: Path) -> Mapping[str, Any]:
    spec = load_research_spec(run_directory / "research-spec.json")
    window = _read_json(run_directory / "research-window.json")
    if window.get("schema") != RESEARCH_WINDOW_SCHEMA:
        raise ExperimentError("research measurement window schema is unsupported")
    start_utc = _utc_seconds(str(window.get("start_utc", "")))
    end_utc = _utc_seconds(str(window.get("end_utc", "")))
    if end_utc <= start_utc:
        raise ExperimentError("research measurement window is invalid")
    telemetry = [
        record
        for record in _read_jsonl(run_directory / "telemetry.jsonl")
        if start_utc <= _utc_seconds(str(record.get("received_at_utc", ""))) < end_utc
    ]
    result = {
        "schema": RESEARCH_RESULT_SCHEMA,
        "campaign_id": spec.campaign_id,
        "run_id": spec.run_id,
        "network_run_id": spec.network_run_id,
        "condition": spec.condition,
        "cooja_seed": spec.cooja_seed,
        "target_fraction": spec.load.target_fraction,
        "telemetry": telemetry_metrics(telemetry, expected_events=spec.expected_events),
        "probe": probe_metrics(_read_jsonl(run_directory / "research-probe.jsonl")),
        "network": network_metrics(_read_jsonl(run_directory / "research-network.jsonl")),
        "load": load_metrics(
            _read_jsonl(run_directory / "research-load.jsonl"),
            target_kbps=spec.load.target_kbps,
        ),
    }
    _atomic_json(run_directory / "research-summary.json", result)
    return result


def _stable_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bootstrap_median_ci(
    values: Sequence[float], *, seed: int, samples: int = 2000
) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    if samples < 100:
        raise ExperimentError("bootstrap requires at least 100 resamples")
    source = [float(value) for value in values]
    rng = random.Random(seed)
    medians = [
        statistics.median(rng.choice(source) for _ in range(len(source)))
        for _ in range(samples)
    ]
    return percentile(medians, 0.025), percentile(medians, 0.975)


def _condition_seed(campaign_id: str, label: str) -> int:
    digest = hashlib.sha256(f"{campaign_id}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def summarize_campaign(
    *, campaign_id: str, run_results: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any]:
    validate_run_id(campaign_id)
    if not run_results:
        raise ExperimentError("campaign analysis requires at least one run result")
    conditions: dict[str, list[Mapping[str, Any]]] = {}
    for result in run_results:
        if result.get("campaign_id") != campaign_id:
            raise ExperimentError("campaign analysis contains a run from another campaign")
        label = f"{result.get('condition')}:{float(result.get('target_fraction', 0.0)):.4f}"
        conditions.setdefault(label, []).append(result)

    summaries: dict[str, Any] = {}
    for label, results in sorted(conditions.items()):
        delivery = [float(item["telemetry"]["delivery_ratio"]) for item in results]
        rtt = [
            float(item["probe"]["rtt_p95_ms"])
            for item in results
            if item.get("probe", {}).get("rtt_p95_ms") is not None
        ]
        delivery_ci = bootstrap_median_ci(
            delivery, seed=_condition_seed(campaign_id, label + ":delivery")
        )
        rtt_ci = bootstrap_median_ci(rtt, seed=_condition_seed(campaign_id, label + ":rtt"))
        summaries[label] = {
            "runs": len(results),
            "delivery_ratio_median": statistics.median(delivery),
            "delivery_ratio_min": min(delivery),
            "delivery_ratio_median_ci95": list(delivery_ci),
            "rtt_p95_median_ms": None if not rtt else statistics.median(rtt),
            "rtt_p95_median_ci95_ms": list(rtt_ci),
        }

    baseline_by_seed = {
        int(item["cooja_seed"]): item
        for item in run_results
        if item.get("condition") == "baseline"
    }
    paired_effects: dict[str, Any] = {}
    for label, results in sorted(conditions.items()):
        if label.startswith("baseline:"):
            continue
        delivery_delta: list[float] = []
        rtt_delta: list[float] = []
        for item in results:
            baseline = baseline_by_seed.get(int(item["cooja_seed"]))
            if baseline is None:
                continue
            delivery_delta.append(
                float(item["telemetry"]["delivery_ratio"])
                - float(baseline["telemetry"]["delivery_ratio"])
            )
            current_rtt = item.get("probe", {}).get("rtt_p95_ms")
            baseline_rtt = baseline.get("probe", {}).get("rtt_p95_ms")
            if current_rtt is not None and baseline_rtt is not None:
                rtt_delta.append(float(current_rtt) - float(baseline_rtt))
        paired_effects[label] = {
            "paired_runs": len(delivery_delta),
            "delivery_ratio_delta_median": None if not delivery_delta else statistics.median(delivery_delta),
            "rtt_p95_delta_median_ms": None if not rtt_delta else statistics.median(rtt_delta),
        }

    payload = {
        "schema": RESEARCH_SUMMARY_SCHEMA,
        "campaign_id": campaign_id,
        "conditions": summaries,
        "paired_effects": paired_effects,
        "run_count": len(run_results),
    }
    return {**payload, "sha256": _stable_hash(payload)}


def write_campaign_parquet(
    results: Sequence[Mapping[str, Any]], destination: Path
) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ExperimentError("PyArrow is required for campaign Parquet output") from exc
    rows: list[dict[str, Any]] = []
    for item in results:
        telemetry = item.get("telemetry") if isinstance(item.get("telemetry"), dict) else {}
        probe = item.get("probe") if isinstance(item.get("probe"), dict) else {}
        network = item.get("network") if isinstance(item.get("network"), dict) else {}
        load = item.get("load") if isinstance(item.get("load"), dict) else {}
        rows.append(
            {
                "campaign_id": str(item.get("campaign_id")),
                "run_id": str(item.get("run_id")),
                "condition": str(item.get("condition")),
                "cooja_seed": int(item.get("cooja_seed", 0)),
                "target_fraction": float(item.get("target_fraction", 0.0)),
                "delivery_ratio": float(telemetry.get("delivery_ratio", 0.0)),
                "sequence_gap_rate": float(telemetry.get("sequence_gap_rate", 0.0)),
                "rtt_median_ms": probe.get("rtt_median_ms"),
                "rtt_p95_ms": probe.get("rtt_p95_ms"),
                "rtt_p99_ms": probe.get("rtt_p99_ms"),
                "rtt_jitter_ms": probe.get("rtt_jitter_ms"),
                "probe_timeout_rate": float(probe.get("probe_timeout_rate", 0.0)),
                "ue_tx_kbps": network.get("ue_tx_kbps"),
                "ue_rx_kbps": network.get("ue_rx_kbps"),
                "target_kbps": float(load.get("target_kbps", 0.0)),
                "measured_kbps_median": load.get("measured_kbps_median"),
            }
        )
    table = pa.Table.from_pylist(rows)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        destination,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
    )


def analyze_campaign(
    *,
    campaign_id: str,
    run_root: Path,
    run_ids: Sequence[str],
    destination: Path,
) -> Mapping[str, Any]:
    results: list[Mapping[str, Any]] = []
    for run_id in run_ids:
        run_directory = run_root / validate_run_id(run_id)
        evidence = _read_json(run_directory / "research-evidence.json")
        if evidence.get("schema") != RESEARCH_EVIDENCE_SCHEMA or evidence.get("valid") is not True:
            raise ExperimentError(f"research run is not valid for campaign analysis: {run_id}")
        results.append(analyze_research_run(run_directory))
    summary = summarize_campaign(campaign_id=campaign_id, run_results=results)
    _atomic_json(destination, summary)
    write_campaign_parquet(results, destination.with_name("campaign-results.parquet"))
    return summary
