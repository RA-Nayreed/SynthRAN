"""Read-only attachment to an accepted SynthRAN testbed deployment.

Physical experiments may consume infrastructure that ``deploy.sh`` has already
accepted, but they must not reserve, repair, rebuild, power-cycle, or otherwise
mutate that infrastructure merely to make an experiment pass. This module
therefore performs identity and compatibility checks only.

An attachment proves that a deployment was accepted and that its saved identity
and evidence are internally consistent. It does *not* prove current radio or UE
liveness; physical experiment phases must collect fresh run-time evidence for
claims that depend on current state.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from synthran.deployment_state import (
    ACTIVE_ENDPOINT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    content_hash,
    validate_live_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_DEPLOYMENT_ENDPOINT = ROOT / ".synthran/active-deployment.json"


class AttachmentError(ValueError):
    """The saved accepted deployment cannot satisfy an experiment contract."""


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AttachmentError(f"{label} is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AttachmentError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AttachmentError(f"{label} must be a JSON object: {path}")
    return value


def _expected(actual: Any, requirement: Any, label: str) -> None:
    """Validate one scalar against either an exact value or an allowed set."""

    if isinstance(requirement, (list, tuple, set, frozenset)):
        if actual not in requirement:
            raise AttachmentError(
                f"accepted deployment {label}={actual!r} is not one of {list(requirement)!r}"
            )
        return
    if actual != requirement:
        raise AttachmentError(
            f"accepted deployment {label}={actual!r} does not match required {requirement!r}"
        )


def _transport_value(binding: dict[str, Any], key: str) -> Any:
    if key in binding:
        return binding.get(key)
    tunnel = binding.get("tunnel", {})
    return tunnel.get(key) if isinstance(tunnel, dict) else None


def _ue_matches(binding: dict[str, Any], requirement: dict[str, Any]) -> bool:
    direct = {
        "device",
        "index",
        "imsi",
        "slice",
        "sst",
        "sd",
        "dnn",
        "address_cidr",
    }
    transport = {"host", "namespace", "interface", "mode", "mbim_session"}
    for key, expected in requirement.items():
        if key in direct:
            actual = binding.get(key)
        elif key in transport:
            actual = _transport_value(binding, key)
        else:
            raise AttachmentError(f"unsupported UE attachment requirement: {key}")
        if isinstance(expected, (list, tuple, set, frozenset)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _slice_matches(candidate: dict[str, Any], requirement: dict[str, Any]) -> bool:
    for key, expected in requirement.items():
        if key not in {"name", "sst", "sd", "dnn", "ip_prefix"}:
            raise AttachmentError(f"unsupported slice attachment requirement: {key}")
        actual = candidate.get(key)
        if isinstance(expected, (list, tuple, set, frozenset)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def validate_requirements(
    deployment: dict[str, Any],
    requirements: dict[str, Any] | None,
    *,
    deployment_hash: str,
) -> None:
    """Validate a declarative experiment requirement against accepted identity."""

    requirements = requirements or {}
    allowed = {
        "deployment_hash",
        "core",
        "ran",
        "platform",
        "radio_unit",
        "network_profile",
        "bridge_enabled",
        "nodes",
        "minimum_ues",
        "ue_devices",
        "exact_ue_devices",
        "ues",
        "slices",
    }
    unknown = sorted(set(requirements) - allowed)
    if unknown:
        raise AttachmentError(
            "unsupported accepted-testbed requirement(s): " + ", ".join(unknown)
        )

    if "deployment_hash" in requirements:
        _expected(deployment_hash, requirements["deployment_hash"], "deployment_hash")
    for key in (
        "core",
        "ran",
        "platform",
        "radio_unit",
        "network_profile",
        "bridge_enabled",
    ):
        if key in requirements:
            _expected(deployment.get(key), requirements[key], key)

    if "nodes" in requirements:
        required_nodes = requirements["nodes"]
        if not isinstance(required_nodes, dict):
            raise AttachmentError("accepted-testbed nodes requirement must be a mapping")
        actual_nodes = deployment.get("nodes", {})
        if not isinstance(actual_nodes, dict):
            raise AttachmentError("accepted deployment node identity is malformed")
        for role, expected in required_nodes.items():
            if role not in actual_nodes:
                raise AttachmentError(f"accepted deployment has no node role {role!r}")
            _expected(actual_nodes[role], expected, f"nodes.{role}")

    bindings = deployment.get("ues", [])
    if not isinstance(bindings, list) or not all(isinstance(item, dict) for item in bindings):
        raise AttachmentError("accepted deployment UE identity is malformed")
    if "minimum_ues" in requirements:
        minimum = requirements["minimum_ues"]
        if not isinstance(minimum, int) or minimum < 0:
            raise AttachmentError("minimum_ues must be a non-negative integer")
        if len(bindings) < minimum:
            raise AttachmentError(
                f"accepted deployment has {len(bindings)} UE(s); at least {minimum} required"
            )

    if "ue_devices" in requirements:
        required_devices = requirements["ue_devices"]
        if not isinstance(required_devices, list) or not all(
            isinstance(value, str) and value for value in required_devices
        ):
            raise AttachmentError("ue_devices must be a non-empty-name list")
        actual_devices = [str(item.get("device")) for item in bindings]
        missing = sorted(set(required_devices) - set(actual_devices))
        if missing:
            raise AttachmentError(
                "accepted deployment is missing required UE device(s): " + ", ".join(missing)
            )
        if requirements.get("exact_ue_devices") is True and set(actual_devices) != set(required_devices):
            raise AttachmentError(
                "accepted deployment UE set differs from the experiment's exact UE set"
            )

    ue_requirements = requirements.get("ues", [])
    if not isinstance(ue_requirements, list):
        raise AttachmentError("accepted-testbed ues requirement must be a list")
    for requirement in ue_requirements:
        if not isinstance(requirement, dict) or not requirement:
            raise AttachmentError("each accepted-testbed UE requirement must be a mapping")
        matches = [item for item in bindings if _ue_matches(item, requirement)]
        if len(matches) != 1:
            raise AttachmentError(
                f"UE requirement {requirement!r} matched {len(matches)} accepted binding(s); expected exactly one"
            )

    slices = deployment.get("slices", [])
    if not isinstance(slices, list) or not all(isinstance(item, dict) for item in slices):
        raise AttachmentError("accepted deployment slice identity is malformed")
    slice_requirements = requirements.get("slices", [])
    if not isinstance(slice_requirements, list):
        raise AttachmentError("accepted-testbed slices requirement must be a list")
    for requirement in slice_requirements:
        if not isinstance(requirement, dict) or not requirement:
            raise AttachmentError("each accepted-testbed slice requirement must be a mapping")
        matches = [item for item in slices if _slice_matches(item, requirement)]
        if len(matches) != 1:
            raise AttachmentError(
                f"slice requirement {requirement!r} matched {len(matches)} accepted slice(s); expected exactly one"
            )


def requirements_from_deployment(deployment: dict[str, Any]) -> dict[str, Any]:
    """Build an exact infrastructure requirement from a resolved scenario."""

    if not isinstance(deployment, dict):
        raise AttachmentError("deployment requirement source must be a mapping")
    required = {
        "core": deployment.get("core"),
        "ran": str(deployment.get("ran", "")).lower(),
        "platform": deployment.get("platform"),
        "radio_unit": (
            "rfsim"
            if deployment.get("platform") == "rfsim"
            else deployment.get("ru", deployment.get("platform"))
        ),
        "network_profile": deployment.get("network_profile"),
        "nodes": copy.deepcopy(deployment.get("nodes", {})),
        "ue_devices": list(deployment.get("ues", [])),
        "exact_ue_devices": True,
    }
    return required


def attach_active_deployment(
    requirements: dict[str, Any] | None = None,
    *,
    endpoint_path: str | Path = ACTIVE_DEPLOYMENT_ENDPOINT,
    evidence_max_age_seconds: int | None = None,
) -> dict[str, Any]:
    """Attach read-only to the currently accepted deployment.

    ``evidence_max_age_seconds`` defaults to ``None`` deliberately. The saved
    live evidence proves the deployment was accepted; it is not treated as a
    fresh liveness measurement. A physical experiment must gather fresh evidence
    for any current-state claim.
    """

    endpoint_path = Path(endpoint_path).resolve()
    endpoint = _read_object(endpoint_path, "active deployment endpoint")
    if endpoint.get("schema_version") != ACTIVE_ENDPOINT_SCHEMA_VERSION:
        raise AttachmentError("active deployment endpoint schema is unsupported")
    if endpoint.get("status") != "active":
        raise AttachmentError("saved deployment endpoint is not active")

    identity_path = Path(str(endpoint.get("identity_file", ""))).resolve()
    evidence_path = Path(str(endpoint.get("evidence_file", ""))).resolve()
    private_dir = Path(str(endpoint.get("private_execution_dir", ""))).resolve()
    result_dir = Path(str(endpoint.get("result_dir", ""))).resolve()
    identity = _read_object(identity_path, "active deployment identity")

    if identity.get("schema_version") != SCHEMA_VERSION:
        raise AttachmentError("active deployment identity schema is unsupported")
    if identity.get("status") != "active":
        raise AttachmentError("active deployment identity is not active")
    deployment = identity.get("deployment")
    if not isinstance(deployment, dict):
        raise AttachmentError("active deployment identity has no deployment mapping")
    observed_hash = content_hash(deployment)
    if identity.get("deployment_hash") != observed_hash:
        raise AttachmentError("active deployment identity failed its integrity check")
    if endpoint.get("deployment_hash") != observed_hash:
        raise AttachmentError("active deployment endpoint and identity hashes differ")

    try:
        evidence = validate_live_evidence(
            identity_path,
            evidence_path,
            max_age_seconds=evidence_max_age_seconds,
        )
    except ValueError as exc:
        raise AttachmentError(str(exc)) from exc

    required_private = (private_dir / "inventory.yml", private_dir / "deployment-vars.yml")
    missing = [str(path) for path in required_private if not path.is_file()]
    if missing:
        raise AttachmentError(
            "accepted deployment execution context is incomplete: " + ", ".join(missing)
        )
    if not result_dir.is_dir():
        raise AttachmentError(f"accepted deployment result directory is missing: {result_dir}")

    validate_requirements(deployment, requirements, deployment_hash=observed_hash)

    return {
        "schema_version": 1,
        "status": "attached",
        "mode": "read_only",
        "deployment_hash": observed_hash,
        "deployment_run_id": endpoint.get("run_id"),
        "endpoint_published_at": endpoint.get("published_at"),
        "deployment_attested_at": identity.get("attested_at"),
        "evidence_observed_at": evidence.get("observed_at"),
        "identity_file": str(identity_path),
        "evidence_file": str(evidence_path),
        "private_execution_dir": str(private_dir),
        "result_dir": str(result_dir),
        "requirements": copy.deepcopy(requirements or {}),
        "deployment": {
            key: copy.deepcopy(deployment.get(key))
            for key in (
                "core",
                "ran",
                "platform",
                "radio_unit",
                "network_profile",
                "bridge_enabled",
                "nodes",
                "slices",
                "ues",
            )
        },
        "claim_boundary": (
            "Attachment proves compatibility with a previously accepted deployment; "
            "it does not prove current RF, UE, session, or user-plane liveness."
        ),
    }
