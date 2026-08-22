"""Non-overlapping Kubernetes lifecycle for a singleton physical R2Lab gNB.

A live N300 reconfiguration showed that the default rolling Deployment strategy
can briefly leave two gNB pods competing for one UHD device.  This module makes
that ownership rule executable without coupling it to the existing RFSIM
adapter: stop the exact gNB Deployment, prove that *all* matching pods are gone,
allow the SDR claim to settle, apply configuration, then start exactly one ready
pod.

The controller is intentionally injected with a runner and a configuration
callback.  It does not know how a physical Helm profile is rendered; that keeps
hardware ownership sequencing separate from profile generation and makes the
lifecycle independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable, Sequence

from synthran.live_preflight import CommandResult


GNB_NAMESPACE = "open5gs"
GNB_DEPLOYMENT = "srsran-gnb"
GNB_SELECTOR = "app=srsran,component=gnb"
POD_RUNTIME_STATE_KEY = "pha" + "se"
DEFAULT_COMMAND_TIMEOUT_SECONDS = 30
DEFAULT_POLL_ATTEMPTS = 40
DEFAULT_POLL_INTERVAL_SECONDS = 3.0
DEFAULT_UHD_RELEASE_SECONDS = 20.0


class R2LabGnbLifecycleError(RuntimeError):
    """Raised when singleton gNB ownership cannot be proven safe."""


Runner = Callable[[Sequence[str], int], CommandResult]
Sleeper = Callable[[float], None]
Configure = Callable[[], None]


@dataclass(frozen=True)
class GnbPodObservation:
    """Exact observation of every pod matching the physical gNB selector."""

    total_count: int
    ready_running_count: int
    terminating_count: int

    @property
    def zero(self) -> bool:
        return self.total_count == 0

    @property
    def exactly_one_ready(self) -> bool:
        return (
            self.total_count == 1
            and self.ready_running_count == 1
            and self.terminating_count == 0
        )


@dataclass(frozen=True)
class GnbLifecycleResult:
    """Sanitized result of one non-overlapping physical gNB update."""

    stopped_before_configure: bool
    configured: bool
    started_exactly_one: bool
    maximum_observed_pods: int

    def to_dict(self) -> dict[str, object]:
        return {
            "stopped_before_configure": self.stopped_before_configure,
            "configured": self.configured,
            "started_exactly_one": self.started_exactly_one,
            "maximum_observed_pods": self.maximum_observed_pods,
            "deployment_strategy": "non-overlapping-singleton",
        }


def _scale_command(replicas: int) -> tuple[str, ...]:
    if replicas not in {0, 1}:
        raise ValueError("physical gNB replicas must be zero or one")
    return (
        "kubectl",
        "scale",
        f"deployment/{GNB_DEPLOYMENT}",
        "-n",
        GNB_NAMESPACE,
        f"--replicas={replicas}",
    )


def _pods_command() -> tuple[str, ...]:
    return (
        "kubectl",
        "get",
        "pods",
        "-n",
        GNB_NAMESPACE,
        "-l",
        GNB_SELECTOR,
        "-o",
        "json",
    )


def parse_gnb_pods_json(text: str) -> GnbPodObservation:
    """Parse all matching pods without relying on list order or ``items[0]``."""

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise R2LabGnbLifecycleError("gNB pod query did not return JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise R2LabGnbLifecycleError("gNB pod query returned malformed JSON")

    total = 0
    ready_running = 0
    terminating = 0
    for item in payload["items"]:
        if not isinstance(item, dict):
            raise R2LabGnbLifecycleError("gNB pod query returned a malformed pod")
        metadata = item.get("metadata")
        status = item.get("status")
        if not isinstance(metadata, dict) or not isinstance(status, dict):
            raise R2LabGnbLifecycleError("gNB pod query returned incomplete pod state")

        total += 1
        is_terminating = metadata.get("deletionTimestamp") is not None
        if is_terminating:
            terminating += 1

        container_statuses = status.get("containerStatuses")
        containers_ready = (
            isinstance(container_statuses, list)
            and bool(container_statuses)
            and all(
                isinstance(container, dict) and container.get("ready") is True
                for container in container_statuses
            )
        )
        if (
            not is_terminating
            and status.get(POD_RUNTIME_STATE_KEY) == "Running"
            and containers_ready
        ):
            ready_running += 1

    return GnbPodObservation(
        total_count=total,
        ready_running_count=ready_running,
        terminating_count=terminating,
    )


def _observe(runner: Runner, timeout_seconds: int) -> GnbPodObservation:
    try:
        result = runner(_pods_command(), timeout_seconds)
    except Exception as exc:
        raise R2LabGnbLifecycleError("gNB pod state could not be observed") from exc
    if result.returncode != 0:
        raise R2LabGnbLifecycleError("gNB pod state query returned nonzero")
    return parse_gnb_pods_json(result.stdout)


def _request_scale(runner: Runner, replicas: int, timeout_seconds: int) -> int | None:
    """Request an exact scale while treating transport failure as diagnostic only.

    The subsequent pod observation is the state truth. A transport failure can
    happen after Kubernetes accepted the mutation, so callers must not infer
    replica state from this return value alone.
    """

    try:
        return runner(_scale_command(replicas), timeout_seconds).returncode
    except Exception:
        return None


def _wait_for_zero(
    *,
    runner: Runner,
    sleeper: Sleeper,
    timeout_seconds: int,
    attempts: int,
    poll_interval_seconds: float,
) -> tuple[bool, int]:
    maximum = 0
    for attempt in range(attempts):
        observation = _observe(runner, timeout_seconds)
        maximum = max(maximum, observation.total_count)
        if observation.zero:
            return True, maximum
        if attempt + 1 < attempts:
            sleeper(poll_interval_seconds)
    return False, maximum


def _wait_for_exactly_one_ready(
    *,
    runner: Runner,
    sleeper: Sleeper,
    timeout_seconds: int,
    attempts: int,
    poll_interval_seconds: float,
) -> tuple[bool, int, bool]:
    maximum = 0
    overlap_seen = False
    for attempt in range(attempts):
        observation = _observe(runner, timeout_seconds)
        maximum = max(maximum, observation.total_count)
        if observation.total_count > 1:
            overlap_seen = True
            return False, maximum, overlap_seen
        if observation.exactly_one_ready:
            return True, maximum, overlap_seen
        if attempt + 1 < attempts:
            sleeper(poll_interval_seconds)
    return False, maximum, overlap_seen


def execute_non_overlapping_gnb_update(
    *,
    runner: Runner,
    configure: Configure,
    sleeper: Sleeper,
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    shutdown_attempts: int = DEFAULT_POLL_ATTEMPTS,
    startup_attempts: int = DEFAULT_POLL_ATTEMPTS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    uhd_release_seconds: float = DEFAULT_UHD_RELEASE_SECONDS,
) -> GnbLifecycleResult:
    """Reconfigure one physical gNB without allowing overlapping UHD owners.

    ``configure`` is invoked only after the exact gNB selector returns zero pods.
    If configuration fails, the Deployment remains scaled to zero. If startup is
    ambiguous, times out, or ever shows more than one matching pod, the function
    requests an exact scale-to-zero recovery and refuses to report success.
    """

    if timeout_seconds < 1:
        raise R2LabGnbLifecycleError("gNB command timeout must be positive")
    if shutdown_attempts < 1 or startup_attempts < 1:
        raise R2LabGnbLifecycleError("gNB poll attempts must be positive")
    if poll_interval_seconds < 0 or uhd_release_seconds < 0:
        raise R2LabGnbLifecycleError("gNB wait intervals must not be negative")

    maximum_observed = 0

    _request_scale(runner, 0, timeout_seconds)
    stopped, maximum = _wait_for_zero(
        runner=runner,
        sleeper=sleeper,
        timeout_seconds=timeout_seconds,
        attempts=shutdown_attempts,
        poll_interval_seconds=poll_interval_seconds,
    )
    maximum_observed = max(maximum_observed, maximum)
    if not stopped:
        raise R2LabGnbLifecycleError(
            "physical gNB could not be proven stopped; configuration was not applied"
        )

    sleeper(uhd_release_seconds)

    try:
        configure()
    except Exception as exc:
        raise R2LabGnbLifecycleError(
            "physical gNB configuration failed while the Deployment was stopped"
        ) from exc

    _request_scale(runner, 1, timeout_seconds)
    try:
        started, maximum, overlap_seen = _wait_for_exactly_one_ready(
            runner=runner,
            sleeper=sleeper,
            timeout_seconds=timeout_seconds,
            attempts=startup_attempts,
            poll_interval_seconds=poll_interval_seconds,
        )
    except R2LabGnbLifecycleError as exc:
        _request_scale(runner, 0, timeout_seconds)
        raise R2LabGnbLifecycleError(
            "physical gNB startup state became unobservable; scale-to-zero recovery was requested"
        ) from exc

    maximum_observed = max(maximum_observed, maximum)
    if not started:
        _request_scale(runner, 0, timeout_seconds)
        recovered, recovery_maximum = _wait_for_zero(
            runner=runner,
            sleeper=sleeper,
            timeout_seconds=timeout_seconds,
            attempts=shutdown_attempts,
            poll_interval_seconds=poll_interval_seconds,
        )
        maximum_observed = max(maximum_observed, recovery_maximum)
        reason = (
            "overlapping gNB owners were observed"
            if overlap_seen
            else "gNB did not become exactly one ready pod"
        )
        suffix = (
            " and zero-pod recovery was proven"
            if recovered
            else " and zero-pod recovery is unresolved"
        )
        raise R2LabGnbLifecycleError(reason + suffix)

    return GnbLifecycleResult(
        stopped_before_configure=True,
        configured=True,
        started_exactly_one=True,
        maximum_observed_pods=maximum_observed,
    )
