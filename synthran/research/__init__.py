"""Controlled research contracts, artifacts, scheduling, and analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import statistics
import tempfile
from typing import Any, Mapping, Sequence

from synthran.experiment import ExperimentError

RESEARCH_EXPERIMENT_SCHEMA = "synthran/research-experiment/v1alpha1"
RESEARCH_CAMPAIGN_SCHEMA = "synthran/research-campaign/v1alpha1"
RESEARCH_SUMMARY_SCHEMA = "synthran/research-summary/v1alpha1"
MEASUREMENT_WINDOW_SCHEMA = "synthran/research-measurement-window/v1alpha1"
PROBE_SCHEMA = "synthran/research-probe/v1alpha1"
NETWORK_SAMPLE_SCHEMA = "synthran/research-network-sample/v1alpha1"
LOAD_RESULT_SCHEMA = "synthran/research-load-result/v1alpha1"
CAPACITY_SCHEMA = "synthran/research-capacity/v1alpha1"
ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
CONDITION_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,31}[a-z0-9])?$")


class ResearchError(ExperimentError):
    """Raised when a controlled research contract or artifact is invalid."""


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as stream:
        json.dump(dict(payload), stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def _identifier(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.fullmatch(value):
        raise ResearchError(f"{label} has unsupported characters or length")
    return value


@dataclass(frozen=True)
class MeasurementSpec:
    warmup_seconds: int = 30
    duration_seconds: int = 180
    sample_interval_seconds: float = 1.0
    probe_interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not 0 <= self.warmup_seconds <= 900:
            raise ResearchError("warmup duration must be between 0 and 900 seconds")
        if not 30 <= self.duration_seconds <= 3600:
            raise ResearchError("measurement duration must be between 30 and 3600 seconds")
        if not 0.2 <= self.sample_interval_seconds <= 60.0:
            raise ResearchError("sample interval must be between 0.2 and 60 seconds")
        if not 0.2 <= self.probe_interval_seconds <= 60.0:
            raise ResearchError("probe interval must be between 0.2 and 60 seconds")

    def to_dict(self) -> dict[str, Any]:
        return {
            "warmup_seconds": self.warmup_seconds,
            "duration_seconds": self.duration_seconds,
            "sample_interval_seconds": self.sample_interval_seconds,
            "probe_interval_seconds": self.probe_interval_seconds,
        }


@dataclass(frozen=True)
class LoadSpec:
    enabled: bool = False
    protocol: str = "udp"
    target_bps: int | None = None
    target_fraction: float | None = None
    reference_capacity_bps: int | None = None
    parallel_flows: int = 1
    server_port: int = 5201

    def __post_init__(self) -> None:
        if self.protocol != "udp":
            raise ResearchError("controlled background load protocol must be udp")
        if not 1 <= self.parallel_flows <= 32:
            raise ResearchError("parallel flows must be between 1 and 32")
        if not 1024 <= self.server_port <= 65535:
            raise ResearchError("load server port must be between 1024 and 65535")
        if not self.enabled:
            if any(
                value is not None
                for value in (
                    self.target_bps,
                    self.target_fraction,
                    self.reference_capacity_bps,
                )
            ):
                raise ResearchError("disabled load must not define a target")
            return
        if (self.target_bps is None) == (self.target_fraction is None):
            raise ResearchError(
                "enabled load requires exactly one target_bps or target_fraction"
            )
        if self.target_bps is not None and self.target_bps <= 0:
            raise ResearchError("target_bps must be positive")
        if self.target_fraction is not None:
            if not 0.0 < self.target_fraction <= 1.0:
                raise ResearchError("target_fraction must be in (0, 1]")
            if not self.reference_capacity_bps or self.reference_capacity_bps <= 0:
                raise ResearchError(
                    "fractional load requires positive reference_capacity_bps"
                )
        elif self.reference_capacity_bps is not None:
            raise ResearchError(
                "reference_capacity_bps is valid only with target_fraction"
            )

    @property
    def resolved_target_bps(self) -> int | None:
        if not self.enabled:
            return None
        if self.target_bps is not None:
            return self.target_bps
        assert self.target_fraction is not None
        assert self.reference_capacity_bps is not None
        return max(1, round(self.reference_capacity_bps * self.target_fraction))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "protocol": self.protocol,
            "target_bps": self.target_bps,
            "target_fraction": self.target_fraction,
            "reference_capacity_bps": self.reference_capacity_bps,
            "resolved_target_bps": self.resolved_target_bps,
            "parallel_flows": self.parallel_flows,
            "server_port": self.server_port,
        }


@dataclass(frozen=True)
class ResearchExperimentSpec:
    campaign_id: str
    run_id: str
    network_run_id: str
    condition: str
    cooja_seed: int = 424242
    sensor_period_seconds: int = 10
    sensor_count: int = 10
    measurement: MeasurementSpec = MeasurementSpec()
    load: LoadSpec = LoadSpec()
    probe_target: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.campaign_id, ID_RE, "campaign ID")
        _identifier(self.run_id, ID_RE, "run ID")
        _identifier(self.network_run_id, ID_RE, "network run ID")
        _identifier(self.condition, CONDITION_RE, "condition")
        if self.cooja_seed < 0:
            raise ResearchError("Cooja seed must be non-negative")
        if not 1 <= self.sensor_period_seconds <= 3600:
            raise ResearchError("sensor period must be between 1 and 3600 seconds")
        if self.sensor_count != 10:
            raise ResearchError("controlled experiment requires exactly 10 sensors")
        if self.condition == "baseline" and self.load.enabled:
            raise ResearchError("baseline condition must not enable background load")
        if self.condition != "baseline" and not self.load.enabled:
            raise ResearchError("non-baseline condition requires an enabled load")
        if self.probe_target is not None and not self.probe_target.strip():
            raise ResearchError("probe target must not be empty")

    @property
    def expected_events_per_sensor(self) -> int:
        return max(1, self.measurement.duration_seconds // self.sensor_period_seconds)

    @property
    def expected_events_total(self) -> int:
        return self.expected_events_per_sensor * self.sensor_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RESEARCH_EXPERIMENT_SCHEMA,
            "campaign_id": self.campaign_id,
            "run_id": self.run_id,
            "network_run_id": self.network_run_id,
            "condition": self.condition,
            "cooja_seed": self.cooja_seed,
            "sensor_period_seconds": self.sensor_period_seconds,
            "sensor_count": self.sensor_count,
            "measurement": self.measurement.to_dict(),
            "load": self.load.to_dict(),
            "probe_target": self.probe_target,
            "expected_events_per_sensor": self.expected_events_per_sensor,
            "expected_events_total": self.expected_events_total,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResearchExperimentSpec":
        if value.get("schema") != RESEARCH_EXPERIMENT_SCHEMA:
            raise ResearchError("research experiment schema is unsupported")
        measurement = value.get("measurement")
        load = value.get("load")
        if not isinstance(measurement, Mapping) or not isinstance(load, Mapping):
            raise ResearchError(
                "research experiment measurement/load sections are malformed"
            )
        return cls(
            campaign_id=str(value.get("campaign_id")),
            run_id=str(value.get("run_id")),
            network_run_id=str(value.get("network_run_id")),
            condition=str(value.get("condition")),
            cooja_seed=int(value.get("cooja_seed", 424242)),
            sensor_period_seconds=int(value.get("sensor_period_seconds", 10)),
            sensor_count=int(value.get("sensor_count", 10)),
            measurement=MeasurementSpec(
                warmup_seconds=int(measurement.get("warmup_seconds", 30)),
                duration_seconds=int(measurement.get("duration_seconds", 180)),
                sample_interval_seconds=float(
                    measurement.get("sample_interval_seconds", 1.0)
                ),
                probe_interval_seconds=float(
                    measurement.get("probe_interval_seconds", 1.0)
                ),
            ),
            load=LoadSpec(
                enabled=bool(load.get("enabled", False)),
                protocol=str(load.get("protocol", "udp")),
                target_bps=(
                    int(load["target_bps"])
                    if load.get("target_bps") is not None
                    else None
                ),
                target_fraction=(
                    float(load["target_fraction"])
                    if load.get("target_fraction") is not None
                    else None
                ),
                reference_capacity_bps=(
                    int(load["reference_capacity_bps"])
                    if load.get("reference_capacity_bps") is not None
                    else None
                ),
                parallel_flows=int(load.get("parallel_flows", 1)),
                server_port=int(load.get("server_port", 5201)),
            ),
            probe_target=(
                str(value["probe_target"])
                if value.get("probe_target") is not None
                else None
            ),
        )


def save_research_spec(spec: ResearchExperimentSpec, path: Path) -> None:
    atomic_json(path, spec.to_dict())


@dataclass(frozen=True)
class CampaignCondition:
    name: str
    load_fraction: float | None = None
    target_bps: int | None = None

    def __post_init__(self) -> None:
        _identifier(self.name, CONDITION_RE, "campaign condition")
        if self.name == "baseline":
            if self.load_fraction is not None or self.target_bps is not None:
                raise ResearchError(
                    "baseline campaign condition cannot define load"
                )
            return
        if (self.load_fraction is None) == (self.target_bps is None):
            raise ResearchError(
                "loaded campaign condition requires one load target"
            )
        if self.load_fraction is not None and not 0.0 < self.load_fraction <= 1.0:
            raise ResearchError("campaign load fraction must be in (0, 1]")
        if self.target_bps is not None and self.target_bps <= 0:
            raise ResearchError("campaign bitrate must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "load_fraction": self.load_fraction,
            "target_bps": self.target_bps,
        }


@dataclass(frozen=True)
class CampaignRun:
    ordinal: int
    block: int
    seed: int
    condition: str
    run_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "block": self.block,
            "seed": self.seed,
            "condition": self.condition,
            "run_id": self.run_id,
        }


@dataclass(frozen=True)
class ResearchCampaign:
    campaign_id: str
    network_run_id: str
    campaign_seed: int
    seeds: tuple[int, ...]
    conditions: tuple[CampaignCondition, ...]
    runs: tuple[CampaignRun, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RESEARCH_CAMPAIGN_SCHEMA,
            "campaign_id": self.campaign_id,
            "network_run_id": self.network_run_id,
            "campaign_seed": self.campaign_seed,
            "seeds": list(self.seeds),
            "conditions": [condition.to_dict() for condition in self.conditions],
            "runs": [run.to_dict() for run in self.runs],
        }


def build_campaign(
    *,
    campaign_id: str,
    network_run_id: str,
    seeds: Sequence[int],
    conditions: Sequence[CampaignCondition],
    campaign_seed: int,
) -> ResearchCampaign:
    _identifier(campaign_id, ID_RE, "campaign ID")
    _identifier(network_run_id, ID_RE, "network run ID")
    if campaign_seed < 0:
        raise ResearchError("campaign randomization seed must be non-negative")
    if not seeds or len(set(seeds)) != len(seeds) or any(seed < 0 for seed in seeds):
        raise ResearchError("campaign seeds must be unique non-negative integers")
    names = [condition.name for condition in conditions]
    if "baseline" not in names or len(names) != len(set(names)):
        raise ResearchError(
            "campaign requires one baseline and unique condition names"
        )
    rng = random.Random(campaign_seed)
    runs: list[CampaignRun] = []
    ordinal = 0
    for block, seed in enumerate(seeds, start=1):
        order = list(conditions)
        rng.shuffle(order)
        for condition in order:
            ordinal += 1
            run_id = f"{campaign_id}-b{block:02d}-{condition.name}"
            _identifier(run_id, ID_RE, "generated campaign run ID")
            runs.append(
                CampaignRun(
                    ordinal=ordinal,
                    block=block,
                    seed=seed,
                    condition=condition.name,
                    run_id=run_id,
                )
            )
    return ResearchCampaign(
        campaign_id=campaign_id,
        network_run_id=network_run_id,
        campaign_seed=campaign_seed,
        seeds=tuple(seeds),
        conditions=tuple(conditions),
        runs=tuple(runs),
    )


def save_campaign(campaign: ResearchCampaign, path: Path) -> None:
    atomic_json(path, campaign.to_dict())


def append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(
            json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n"
        )
        stream.flush()


def load_jsonl(
    path: Path, *, schema: str | None = None
) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise ResearchError(f"unable to read {path.name}") from exc
    result: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ResearchError(f"{path.name} line {number} is invalid JSON") from exc
        if not isinstance(value, dict) or (
            schema is not None and value.get("schema") != schema
        ):
            raise ResearchError(
                f"{path.name} line {number} has an unsupported record"
            )
        result.append(value)
    return result


def _stats(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "mean": None, "p95": None, "p99": None}
    ordered = sorted(float(value) for value in values)

    def percentile(q: float) -> float:
        position = (len(ordered) - 1) * q
        lower = int(position)
        upper = min(len(ordered) - 1, lower + 1)
        fraction = position - lower
        return ordered[lower] * (1 - fraction) + ordered[upper] * fraction

    return {
        "median": statistics.median(ordered),
        "mean": statistics.fmean(ordered),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
    }


def telemetry_metrics(
    records: Sequence[Mapping[str, Any]],
    *,
    sensor_count: int,
    expected_per_sensor: int,
) -> dict[str, Any]:
    if sensor_count <= 0 or expected_per_sensor <= 0:
        raise ResearchError("telemetry metric expectations must be positive")
    groups = {
        f"sensor-{index:02d}": [] for index in range(1, sensor_count + 1)
    }
    for record in records:
        sensor = record.get("sensor_id")
        if sensor not in groups:
            raise ResearchError(
                "telemetry contains a sensor outside the experiment contract"
            )
        groups[str(sensor)].append(record)
    gaps = duplicates = 0
    arrivals: list[float] = []
    per_sensor: dict[str, Any] = {}
    for sensor, items in groups.items():
        sequences = [int(item["sequence"]) for item in items]
        unique = sorted(set(sequences))
        duplicate_count = len(sequences) - len(unique)
        gap_count = (
            max(0, unique[-1] - unique[0] + 1 - len(unique)) if unique else 0
        )
        duplicates += duplicate_count
        gaps += gap_count
        times = sorted(
            datetime.fromisoformat(
                str(item["received_at_utc"]).replace("Z", "+00:00")
            )
            .astimezone(timezone.utc)
            .timestamp()
            for item in items
        )
        deltas = [
            (right - left) * 1000.0 for left, right in zip(times, times[1:])
        ]
        arrivals.extend(deltas)
        per_sensor[sensor] = {
            "received": len(items),
            "expected": expected_per_sensor,
            "delivery_ratio": min(1.0, len(items) / expected_per_sensor),
            "sequence_gaps": gap_count,
            "duplicate_sequences": duplicate_count,
            "inter_arrival_ms": _stats(deltas),
        }
    expected = sensor_count * expected_per_sensor
    return {
        "expected_events": expected,
        "received_events": len(records),
        "delivery_ratio": min(1.0, len(records) / expected),
        "sequence_gaps": gaps,
        "duplicate_sequences": duplicates,
        "inter_arrival_ms": _stats(arrivals),
        "per_sensor": per_sensor,
    }


def probe_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rtts = [
        float(item["rtt_ms"])
        for item in records
        if item.get("timeout") is not True and item.get("rtt_ms") is not None
    ]
    timeouts = sum(item.get("timeout") is True for item in records)
    jitter = [abs(right - left) for left, right in zip(rtts, rtts[1:])]
    return {
        "samples": len(records),
        "successful": len(rtts),
        "timeouts": timeouts,
        "timeout_ratio": timeouts / len(records) if records else None,
        "rtt_ms": _stats(rtts),
        "rtt_jitter_ms": _stats(jitter),
    }


def load_metrics(
    records: Sequence[Mapping[str, Any]], *, target_bps: int | None
) -> dict[str, Any]:
    measured = [
        float(item["bits_per_second"])
        for item in records
        if isinstance(item.get("bits_per_second"), (int, float))
    ]
    stats = _stats(measured)
    mean = stats["mean"]
    return {
        "target_bps": target_bps,
        "measured_bps": stats,
        "target_ratio": (
            float(mean) / target_bps if mean is not None and target_bps else None
        ),
    }


def _counter_delta(
    first: Mapping[str, Any], last: Mapping[str, Any], key: str
) -> int | None:
    if key not in first or key not in last:
        return None
    try:
        delta = int(last[key]) - int(first[key])
    except (TypeError, ValueError) as exc:
        raise ResearchError(f"network sample counter {key} is invalid") from exc
    if delta < 0:
        raise ResearchError(f"network sample counter {key} decreased")
    return delta


def network_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(records) < 2:
        return {
            "samples": len(records),
            "transport_path_complete": False,
            "ue_tx_bytes_delta": None,
            "ue_rx_bytes_delta": None,
            "ue_tx_bps": None,
            "ue_rx_bps": None,
        }
    ordered = sorted(records, key=lambda item: float(item["elapsed_seconds"]))
    first, last = ordered[0], ordered[-1]
    elapsed = float(last["elapsed_seconds"]) - float(first["elapsed_seconds"])
    if elapsed <= 0:
        raise ResearchError("network sample interval is invalid")
    deltas = {
        key: _counter_delta(first, last, key)
        for key in (
            "ue_tx_bytes",
            "ue_rx_bytes",
            "ue_tx_packets",
            "ue_rx_packets",
            "ue_tx_dropped",
            "ue_rx_dropped",
            "upf_tx_bytes",
            "upf_rx_bytes",
            "upf_tx_packets",
            "upf_rx_packets",
            "upf_tx_dropped",
            "upf_rx_dropped",
            "ingress_accepted_connections",
            "ingress_upstream_bytes",
            "ingress_downstream_bytes",
        )
    }
    complete_keys = (
        "ue_tx_bytes",
        "ue_rx_bytes",
        "upf_tx_bytes",
        "upf_rx_bytes",
        "ingress_accepted_connections",
        "ingress_upstream_bytes",
        "ingress_downstream_bytes",
    )
    complete = all(deltas[key] is not None for key in complete_keys)
    result: dict[str, Any] = {
        "samples": len(records),
        "elapsed_seconds": elapsed,
        "transport_path_complete": complete,
    }
    for key, value in deltas.items():
        result[f"{key}_delta"] = value
    for prefix in ("ue_tx", "ue_rx", "upf_tx", "upf_rx"):
        byte_delta = deltas[f"{prefix}_bytes"]
        result[f"{prefix}_bps"] = (
            byte_delta * 8.0 / elapsed if byte_delta is not None else None
        )
    return result


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_run_summary(
    *,
    spec: ResearchExperimentSpec,
    run_directory: Path,
    telemetry_records: Sequence[Mapping[str, Any]],
    probe_records: Sequence[Mapping[str, Any]],
    network_records: Sequence[Mapping[str, Any]],
    load_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    telemetry = telemetry_metrics(
        telemetry_records,
        sensor_count=spec.sensor_count,
        expected_per_sensor=spec.expected_events_per_sensor,
    )
    probe = probe_metrics(probe_records)
    network = network_metrics(network_records)
    load = load_metrics(load_records, target_bps=spec.load.resolved_target_bps)
    load_valid = (
        True
        if not spec.load.enabled
        else isinstance(load["target_ratio"], float)
        and 0.90 <= load["target_ratio"] <= 1.10
    )
    validity = {
        "telemetry_present": telemetry["received_events"] > 0,
        "probe_present": probe["samples"] > 0,
        "network_samples_present": network["samples"] >= 2,
        "transport_path_sampled": network["transport_path_complete"] is True,
        "load_target_achieved": load_valid,
    }
    hashes: dict[str, str] = {}
    for name in (
        "experiment-spec.json",
        "measurement-window.json",
        "telemetry.jsonl",
        "probe.jsonl",
        "network-samples.jsonl",
        "load.jsonl",
    ):
        path = run_directory / name
        if path.is_file():
            hashes[name] = _hash(path)
    return {
        "schema": RESEARCH_SUMMARY_SCHEMA,
        "campaign_id": spec.campaign_id,
        "run_id": spec.run_id,
        "network_run_id": spec.network_run_id,
        "condition": spec.condition,
        "cooja_seed": spec.cooja_seed,
        "load": spec.load.to_dict(),
        "telemetry": telemetry,
        "probe": probe,
        "network": network,
        "load_result": load,
        "validity": validity,
        "ready_for_campaign_analysis": all(validity.values()),
        "artifact_sha256": hashes,
    }


def save_run_summary(summary: Mapping[str, Any], path: Path) -> None:
    atomic_json(path, summary)


def load_run_summary(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (
        FileNotFoundError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ResearchError(f"unable to read run summary {path}") from exc
    if not isinstance(value, dict) or value.get("schema") != RESEARCH_SUMMARY_SCHEMA:
        raise ResearchError(f"run summary {path} has an unsupported schema")
    return value


def write_records_parquet(
    records: Sequence[Mapping[str, Any]], path: Path
) -> None:
    if not records:
        return
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ResearchError(
            "PyArrow is required for research Parquet output"
        ) from exc
    rows = [dict(item) for item in records]
    rows.sort(
        key=lambda item: (
            float(item.get("elapsed_seconds", 0.0)),
            int(item.get("sequence", 0)),
            str(item.get("sensor_id", "")),
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows),
        path,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
    )


def _metric(summary: Mapping[str, Any], path: Sequence[str]) -> float | None:
    current: Any = summary
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    if isinstance(current, (int, float)) and not isinstance(current, bool):
        return float(current)
    return None


def _aggregate_stats(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "mean": None, "p95": None}
    ordered = sorted(float(value) for value in values)
    index = (len(ordered) - 1) * 0.95
    lower = int(index)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = index - lower
    p95 = ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
    return {
        "median": statistics.median(ordered),
        "mean": statistics.fmean(ordered),
        "p95": p95,
    }


def bootstrap_paired_difference(
    baseline: Sequence[float],
    treatment: Sequence[float],
    *,
    seed: int,
    samples: int = 5000,
) -> dict[str, float | None]:
    if len(baseline) != len(treatment):
        raise ResearchError("paired samples must have the same length")
    if not baseline:
        return {
            "median_difference": None,
            "ci95_low": None,
            "ci95_high": None,
        }
    differences = [right - left for left, right in zip(baseline, treatment)]
    median = statistics.median(differences)
    if len(differences) == 1:
        return {
            "median_difference": median,
            "ci95_low": median,
            "ci95_high": median,
        }
    rng = random.Random(seed)
    boot = sorted(
        statistics.median(
            [differences[rng.randrange(len(differences))] for _ in differences]
        )
        for _ in range(samples)
    )
    return {
        "median_difference": median,
        "ci95_low": boot[round((len(boot) - 1) * 0.025)],
        "ci95_high": boot[round((len(boot) - 1) * 0.975)],
    }


def analyze_campaign(
    campaign: ResearchCampaign, summaries: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    usable = [
        item
        for item in summaries
        if item.get("ready_for_campaign_analysis") is True
        and item.get("campaign_id") == campaign.campaign_id
    ]
    indexed: dict[tuple[int, str], Mapping[str, Any]] = {}
    for item in usable:
        seed, condition = item.get("cooja_seed"), item.get("condition")
        if not isinstance(seed, int) or not isinstance(condition, str):
            raise ResearchError("run summary is missing seed or condition")
        if (seed, condition) in indexed:
            raise ResearchError(
                "campaign contains duplicate seed/condition summaries"
            )
        indexed[(seed, condition)] = item
    paths = {
        "delivery_ratio": ("telemetry", "delivery_ratio"),
        "rtt_median_ms": ("probe", "rtt_ms", "median"),
        "rtt_p95_ms": ("probe", "rtt_ms", "p95"),
        "rtt_jitter_median_ms": ("probe", "rtt_jitter_ms", "median"),
        "inter_arrival_p95_ms": ("telemetry", "inter_arrival_ms", "p95"),
        "background_goodput_bps": (
            "load_result",
            "measured_bps",
            "mean",
        ),
        "ue_tx_bps": ("network", "ue_tx_bps"),
    }
    aggregate: dict[str, Any] = {}
    paired: dict[str, Any] = {}
    for condition in campaign.conditions:
        values = {name: [] for name in paths}
        for seed in campaign.seeds:
            summary = indexed.get((seed, condition.name))
            if summary:
                for name, path in paths.items():
                    value = _metric(summary, path)
                    if value is not None:
                        values[name].append(value)
        aggregate[condition.name] = {
            name: {"n": len(items), **_aggregate_stats(items)}
            for name, items in values.items()
        }
        if condition.name == "baseline":
            continue
        paired_metrics: dict[str, Any] = {}
        for name, path in paths.items():
            left: list[float] = []
            right: list[float] = []
            for seed in campaign.seeds:
                baseline = indexed.get((seed, "baseline"))
                treatment = indexed.get((seed, condition.name))
                if baseline and treatment:
                    a = _metric(baseline, path)
                    b = _metric(treatment, path)
                    if a is not None and b is not None:
                        left.append(a)
                        right.append(b)
            paired_metrics[name] = {
                "n_pairs": len(left),
                **bootstrap_paired_difference(
                    left,
                    right,
                    seed=campaign.campaign_seed + len(name) + len(condition.name),
                ),
            }
        paired[condition.name] = paired_metrics
    return {
        "schema": "synthran/research-campaign-analysis/v1alpha1",
        "campaign_id": campaign.campaign_id,
        "network_run_id": campaign.network_run_id,
        "campaign_seed": campaign.campaign_seed,
        "usable_runs": len(usable),
        "expected_runs": len(campaign.runs),
        "conditions": aggregate,
        "paired_vs_baseline": paired,
    }


__all__ = [
    "CAPACITY_SCHEMA",
    "LOAD_RESULT_SCHEMA",
    "MEASUREMENT_WINDOW_SCHEMA",
    "NETWORK_SAMPLE_SCHEMA",
    "PROBE_SCHEMA",
    "RESEARCH_CAMPAIGN_SCHEMA",
    "RESEARCH_EXPERIMENT_SCHEMA",
    "RESEARCH_SUMMARY_SCHEMA",
    "CampaignCondition",
    "CampaignRun",
    "LoadSpec",
    "MeasurementSpec",
    "ResearchCampaign",
    "ResearchError",
    "ResearchExperimentSpec",
    "analyze_campaign",
    "append_jsonl",
    "atomic_json",
    "bootstrap_paired_difference",
    "build_campaign",
    "build_run_summary",
    "load_jsonl",
    "load_metrics",
    "load_run_summary",
    "network_metrics",
    "probe_metrics",
    "save_campaign",
    "save_research_spec",
    "save_run_summary",
    "telemetry_metrics",
    "write_records_parquet",
]
