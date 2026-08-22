"""Guarded live staging of a validated physical chart with the gNB stopped.

This is the first cluster-mutating boundary for the physical adapter.  It does
*not* start the gNB and does not touch R2Lab hardware.  It transfers a reviewed,
digest-bound chart artifact to the exact SLICES control-plane node, verifies the
remote hashes, and performs one Helm upgrade/install whose generated values keep
the gNB Deployment at zero replicas.

Fresh SLICES reservation/allocation authority, strict known-host SSH, run-owned
Open5GS namespace ownership, and zero existing gNB pods are required before the
Helm mutation.  The later singleton lifecycle is responsible for any scale to
one after R2Lab/N300 authority is independently proven.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
from typing import Callable, Sequence

from synthran.dependencies import DependencyLock
from synthran.live_preflight import (
    CommandResult,
    verify_allocations,
    verify_reservation,
)
from synthran.network.r2lab_physical_artifact import PhysicalChartArtifact
from synthran.network.r2lab_physical_helm import PhysicalHelmRenderEvidence
from synthran.network.runtime import validate_run_id


CORE_NODE = "sopnode-f2"
RAN_NODE = "sopnode-f3"
NAMESPACE = "open5gs"
RELEASE = "srsran-gnb"
GNB_SELECTOR = "app=srsran,component=gnb"
DEFAULT_TIMEOUT_SECONDS = 120
_SAFE_AUTHORITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class R2LabPhysicalStagingError(RuntimeError):
    """Raised when stopped physical chart staging cannot proceed safely."""


Runner = Callable[[Sequence[str], int], CommandResult]


@dataclass(frozen=True)
class PhysicalStagingResult:
    run_id: str
    package_sha256: str
    values_sha256: str
    render_sha256: str
    namespace_owned: bool
    desired_replicas: int
    gnb_pod_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "package_sha256": self.package_sha256,
            "values_sha256": self.values_sha256,
            "render_sha256": self.render_sha256,
            "namespace_owned": self.namespace_owned,
            "desired_replicas": self.desired_replicas,
            "gnb_pod_count": self.gnb_pod_count,
            "status": "staged-stopped",
            "hardware_mutation": False,
        }


def _validate_authority(value: str, label: str) -> str:
    if not _SAFE_AUTHORITY_RE.fullmatch(value):
        raise R2LabPhysicalStagingError(f"{label} contains unsafe characters")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise R2LabPhysicalStagingError("unable to hash physical staging artifact") from exc
    return digest.hexdigest()


def _strict_ssh_base(known_hosts: Path) -> tuple[str, ...]:
    return (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        f"root@{CORE_NODE}",
    )


def _strict_scp_base(known_hosts: Path) -> tuple[str, ...]:
    return (
        "scp",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
    )


def _ssh(known_hosts: Path, *remote: str) -> tuple[str, ...]:
    return (*_strict_ssh_base(known_hosts), shlex.join(remote))


def _checked(runner: Runner, command: Sequence[str], timeout_seconds: int, label: str) -> CommandResult:
    try:
        result = runner(command, timeout_seconds)
    except Exception as exc:
        raise R2LabPhysicalStagingError(f"{label} could not be observed") from exc
    if result.returncode != 0:
        raise R2LabPhysicalStagingError(f"{label} returned nonzero")
    return result


def _locked_helm_version(lock: DependencyLock) -> str:
    tools = lock.raw.get("tools")
    entry = tools.get("helm_linux_amd64") if isinstance(tools, dict) else None
    version = entry.get("version") if isinstance(entry, dict) else None
    if not isinstance(version, str) or not version:
        raise R2LabPhysicalStagingError("dependency lock does not define Helm")
    return version


def _parse_pods(text: str) -> int:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise R2LabPhysicalStagingError("gNB pod query did not return JSON") from exc
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise R2LabPhysicalStagingError("gNB pod query returned malformed JSON")
    return len(items)


def execute_stopped_physical_staging(
    *,
    lock: DependencyLock,
    artifact: PhysicalChartArtifact,
    render_evidence: PhysicalHelmRenderEvidence,
    run_id: str,
    owner: str,
    reservation_id: str,
    allocation_id: str,
    known_hosts: Path,
    now: datetime,
    runner: Runner,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> PhysicalStagingResult:
    """Stage the exact physical Helm release at zero replicas; never start hardware."""

    try:
        run_id = validate_run_id(run_id)
    except Exception as exc:
        raise R2LabPhysicalStagingError(str(exc)) from exc
    owner = _validate_authority(owner, "owner")
    reservation_id = _validate_authority(reservation_id, "reservation ID")
    allocation_id = _validate_authority(allocation_id, "allocation ID")
    if artifact.run_id != run_id:
        raise R2LabPhysicalStagingError("physical artifact run ID does not match staging run")
    if render_evidence.replicas != 0 or render_evidence.strategy != "Recreate":
        raise R2LabPhysicalStagingError("physical render evidence is not stopped and singleton-safe")
    if timeout_seconds < 30 or timeout_seconds > 600:
        raise R2LabPhysicalStagingError("staging timeout must be between 30 and 600 seconds")

    known_hosts = known_hosts.expanduser().resolve()
    if not known_hosts.is_file():
        raise R2LabPhysicalStagingError("strict SLICES known-hosts file is missing")
    if not artifact.package_path.is_file() or not artifact.values_path.is_file():
        raise R2LabPhysicalStagingError("physical artifact files are missing")
    if _sha256_file(artifact.package_path) != artifact.package_sha256:
        raise R2LabPhysicalStagingError("physical chart package digest changed after review")
    if _sha256_file(artifact.values_path) != artifact.values_sha256:
        raise R2LabPhysicalStagingError("physical chart values digest changed after review")

    # Fresh local SLICES authority before any remote write or cluster mutation.
    try:
        verify_reservation(
            runner=runner,
            reservation_id=reservation_id,
            owner=owner,
            nodes={CORE_NODE, RAN_NODE},
            now=now,
            timeout_seconds=min(timeout_seconds, 60),
        )
        verify_allocations(
            runner=runner,
            allocation_id=allocation_id,
            owner=owner,
            nodes={CORE_NODE, RAN_NODE},
            timeout_seconds=min(timeout_seconds, 60),
        )
    except Exception as exc:
        raise R2LabPhysicalStagingError("fresh SLICES authority was not proven") from exc

    remote_root = f"/root/.synthran/{run_id}/physical-chart"
    remote_package = f"{remote_root}/{artifact.package_path.name}"
    remote_values = f"{remote_root}/{artifact.values_path.name}"

    _checked(
        runner,
        _ssh(known_hosts, "mkdir", "-p", remote_root),
        min(timeout_seconds, 60),
        "remote physical artifact directory creation",
    )
    _checked(
        runner,
        (
            *_strict_scp_base(known_hosts),
            str(artifact.package_path),
            str(artifact.values_path),
            f"root@{CORE_NODE}:{remote_root}/",
        ),
        timeout_seconds,
        "strict physical artifact transfer",
    )

    hashes = _checked(
        runner,
        _ssh(known_hosts, "sha256sum", remote_package, remote_values),
        min(timeout_seconds, 60),
        "remote physical artifact digest verification",
    ).stdout
    if artifact.package_sha256 not in hashes or artifact.values_sha256 not in hashes:
        raise R2LabPhysicalStagingError("remote physical artifact digests do not match review")

    helm_version = _checked(
        runner,
        _ssh(known_hosts, "helm", "version", "--short"),
        min(timeout_seconds, 60),
        "remote Helm version probe",
    ).stdout
    expected_helm = _locked_helm_version(lock)
    match = re.search(r"v?([0-9]+\.[0-9]+\.[0-9]+)", helm_version)
    if match is None or match.group(1) != expected_helm:
        raise R2LabPhysicalStagingError(
            f"remote Helm must exactly match locked version {expected_helm}"
        )

    namespace_owner = _checked(
        runner,
        _ssh(
            known_hosts,
            "kubectl",
            "get",
            "namespace",
            NAMESPACE,
            "-o",
            "jsonpath={.metadata.labels.synthran\\.run/id}",
        ),
        min(timeout_seconds, 60),
        "Open5GS namespace ownership query",
    ).stdout.strip()
    if namespace_owner != run_id:
        raise R2LabPhysicalStagingError("Open5GS namespace is not owned by this physical run")

    existing = _checked(
        runner,
        _ssh(
            known_hosts,
            "kubectl",
            "get",
            f"deployment/{RELEASE}",
            "-n",
            NAMESPACE,
            "--ignore-not-found",
            "-o",
            "json",
        ),
        min(timeout_seconds, 60),
        "existing physical gNB Deployment query",
    ).stdout.strip()
    if existing:
        try:
            payload = json.loads(existing)
            desired = payload["spec"]["replicas"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise R2LabPhysicalStagingError("existing gNB Deployment state is malformed") from exc
        if desired != 0:
            raise R2LabPhysicalStagingError(
                "existing physical gNB is not stopped; staging refuses to reconfigure it"
            )

    existing_pods = _parse_pods(
        _checked(
            runner,
            _ssh(
                known_hosts,
                "kubectl",
                "get",
                "pods",
                "-n",
                NAMESPACE,
                "-l",
                GNB_SELECTOR,
                "-o",
                "json",
            ),
            min(timeout_seconds, 60),
            "existing physical gNB pod query",
        ).stdout
    )
    if existing_pods != 0:
        raise R2LabPhysicalStagingError(
            "existing physical gNB pods remain; staging requires zero pods"
        )

    # Recheck allocation authority immediately before the cluster mutation.
    try:
        verify_allocations(
            runner=runner,
            allocation_id=allocation_id,
            owner=owner,
            nodes={CORE_NODE, RAN_NODE},
            timeout_seconds=min(timeout_seconds, 60),
        )
    except Exception as exc:
        raise R2LabPhysicalStagingError(
            "SLICES allocation authority changed before Helm staging"
        ) from exc

    _checked(
        runner,
        _ssh(
            known_hosts,
            "helm",
            "upgrade",
            "--install",
            RELEASE,
            remote_package,
            "--namespace",
            NAMESPACE,
            "--values",
            remote_values,
            "--wait",
            "--atomic",
            "--timeout",
            "120s",
        ),
        timeout_seconds,
        "stopped physical Helm staging",
    )

    deployment = _checked(
        runner,
        _ssh(
            known_hosts,
            "kubectl",
            "get",
            f"deployment/{RELEASE}",
            "-n",
            NAMESPACE,
            "-o",
            "json",
        ),
        min(timeout_seconds, 60),
        "staged physical gNB Deployment query",
    ).stdout
    try:
        desired = json.loads(deployment)["spec"]["replicas"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise R2LabPhysicalStagingError("staged gNB Deployment state is malformed") from exc
    pods = _parse_pods(
        _checked(
            runner,
            _ssh(
                known_hosts,
                "kubectl",
                "get",
                "pods",
                "-n",
                NAMESPACE,
                "-l",
                GNB_SELECTOR,
                "-o",
                "json",
            ),
            min(timeout_seconds, 60),
            "staged physical gNB pod query",
        ).stdout
    )
    if desired != 0 or pods != 0:
        raise R2LabPhysicalStagingError(
            "physical chart staging did not remain at proven zero-pod state"
        )

    return PhysicalStagingResult(
        run_id=run_id,
        package_sha256=artifact.package_sha256,
        values_sha256=artifact.values_sha256,
        render_sha256=render_evidence.sha256,
        namespace_owned=True,
        desired_replicas=desired,
        gnb_pod_count=pods,
    )
