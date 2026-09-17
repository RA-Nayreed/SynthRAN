from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

from .cluster_identity import selected_cluster_runtime, validate_current_cluster
from .deployment_state import content_hash

ROOT = Path(__file__).resolve().parents[1]
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _json_object(path: str | Path, label: str) -> dict[str, Any]:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _yaml_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a YAML mapping: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iter_files(entries: Iterable[Path]) -> list[Path]:
    files: set[Path] = set()
    for entry in entries:
        if entry.is_file():
            files.add(entry.resolve())
        elif entry.is_dir():
            for path in entry.rglob("*"):
                if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts:
                    files.add(path.resolve())
    return sorted(files, key=lambda path: str(path.relative_to(ROOT)))


def selected_adapter_identity(deployment: dict[str, Any]) -> dict[str, Any]:
    """Hash only executable files that can change the selected deployment/acceptance path."""

    core = str(deployment.get("core", "")).lower()
    ran = str(deployment.get("ran", "")).lower()
    platform = str(deployment.get("platform", "")).lower()
    ran_path = "srsRAN" if ran == "srsran" else ran

    entries = [
        ROOT / "pyproject.toml",
        ROOT / "deploy.sh",
        ROOT / "deployment/ansible.cfg",
        ROOT / "deployment/collections/requirements.yml",
        ROOT / "deployment/scripts/run_deployment.sh",
        ROOT / "deployment/scripts/collect_cluster_snapshot.py",
        ROOT / "deployment/playbooks/site.yml",
        ROOT / "deployment/playbooks/acceptance.yml",
        ROOT / "deployment/playbooks/provision_nodes.yml",
        ROOT / "deployment/playbooks/provision_r2lab.yml",
        ROOT / "deployment/playbooks/bootstrap_nodes.yml",
        ROOT / "deployment/playbooks/network.yml",
        ROOT / "deployment/playbooks/attest_transport.yml",
        ROOT / "deployment/playbooks/attest_deployment.yml",
        ROOT / "deployment/playbooks/connect_ues.yml",
        ROOT / "deployment/playbooks/provenance.yml",
        ROOT / "deployment/topology.yml",
        ROOT / "deployment/group_vars/all/all.yml",
        ROOT / "deployment/roles/setup",
        ROOT / "deployment/roles/5g" / core,
        ROOT / "deployment/roles/5g" / ran_path,
        ROOT / "synthran/scenario.py",
        ROOT / "synthran/profile_validation.py",
        ROOT / "synthran/inventory.py",
        ROOT / "synthran/deployment_state.py",
        ROOT / "synthran/cluster_identity.py",
        ROOT / "synthran/deployment_identity.py",
        ROOT / "synthran/acceptance.py",
    ]
    if platform == "r2lab":
        entries.extend(
            [
                ROOT / "deployment/scripts/probe_r2lab_ue.py",
                ROOT / "deployment/roles/r2lab",
                ROOT / "deployment/roles/synthran/r2lab_ue_verify",
                ROOT / "synthran/r2lab.py",
            ]
        )
    elif platform == "rfsim":
        entries.append(ROOT / "deployment/scripts/probe_software_ues.py")

    files = _iter_files(entries)
    if not files:
        raise ValueError("selected deployment adapter identity contains no files")
    records = [
        {"path": str(path.relative_to(ROOT)), "sha256": _sha256_file(path)}
        for path in files
    ]
    return {"sha256": content_hash(records), "file_count": len(records)}


def execution_reference() -> dict[str, str]:
    value = _json_object(
        ROOT / "third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json",
        "reviewed execution reference",
    )
    repository = str(value.get("repository", ""))
    commit = str(value.get("commit", "")).lower()
    if repository != "https://github.com/sopnode/5g_ansible" or not _GIT_SHA_RE.fullmatch(commit):
        raise ValueError("reviewed 5g-Ansible execution reference is not immutable")
    return {"repository": repository, "commit": commit}


def _source_pin(repository: Any, revision: Any, label: str) -> dict[str, str]:
    repository = str(repository or "")
    revision = str(revision or "").lower()
    if not repository or not _GIT_SHA_RE.fullmatch(revision):
        raise ValueError(f"{label} source identity is not an immutable Git revision")
    return {"repository": repository, "revision": revision}


def selected_source_pins(deployment: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    core = str(deployment.get("core", "")).lower()
    ran = str(deployment.get("ran", "")).lower()
    pins: dict[str, Any] = {"lifecycle": execution_reference()}

    if core == "open5gs":
        defaults = _yaml_object(
            ROOT / "deployment/roles/5g/open5gs/config/defaults/main.yml",
            "Open5GS source defaults",
        )
        pins["open5gs"] = _source_pin(
            defaults.get("repo_url"), defaults.get("repo_branch"), "Open5GS"
        )

    if core == "free5gc" or (ran == "ueransim" and core != "open5gs"):
        defaults = _yaml_object(
            ROOT / "deployment/roles/5g/free5gc/config/defaults/main.yml",
            "Free5GC source defaults",
        )
        pins["free5gc"] = _source_pin(
            defaults.get("free5gc_repo_url"),
            defaults.get("free5gc_repo_branch"),
            "Free5GC",
        )

    if ran == "srsran":
        defaults = _yaml_object(
            ROOT / "deployment/roles/5g/srsRAN/common/defaults/main.yml",
            "srsRAN source defaults",
        )
        pins["srsran_chart"] = _source_pin(
            defaults.get("repo_url"), defaults.get("version"), "srsRAN chart"
        )

    if core == "oai" or ran == "oai":
        observed = _json_object(run_dir / "provenance/oai-sources.json", "OAI source provenance")
        pins["oai_helper"] = _source_pin(
            "https://github.com/sopnode/oai5g-rru.git",
            observed.get("oai5g_rru_revision"),
            "OAI helper",
        )
        pins["oai_charts"] = _source_pin(
            "https://gitlab.eurecom.fr/turletti/charts.git",
            observed.get("oai_charts_revision"),
            "OAI charts",
        )

    return pins


def controller_source_provenance(run_dir: Path) -> dict[str, Any]:
    value = _json_object(run_dir / "provenance/controller.json", "controller provenance")
    source = value.get("source")
    if not isinstance(source, dict):
        raise ValueError("controller provenance has no source identity")
    return {
        "revision": str(source.get("revision", "")),
        "dirty_worktree": bool(source.get("dirty_worktree")),
        "worktree_status_sha256": source.get("worktree_status_sha256"),
    }


def selected_cluster_runtime_identity(
    deployment: dict[str, Any], run_dir: Path
) -> dict[str, Any]:
    snapshot = _json_object(run_dir / "provenance/cluster.json", "cluster runtime provenance")
    return selected_cluster_runtime(deployment, snapshot)


def validate_current_cluster_runtime(
    identity: dict[str, Any], provenance_path: str | Path
) -> dict[str, Any]:
    snapshot = _json_object(provenance_path, "fresh cluster runtime provenance")
    return validate_current_cluster(identity, snapshot)


def selected_runtime_refs(deployment: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    ran = str(deployment.get("ran", "")).lower()
    platform = str(deployment.get("platform", "")).lower()
    result: dict[str, Any] = {}
    if ran == "srsran":
        value = _json_object(run_dir / "provenance/srsran-runtime.json", "srsRAN runtime provenance")
        resolved_image = str(value.get("resolved_image", ""))
        sidecar_image = str(value.get("log_sidecar_image", ""))
        chart_revision = str(value.get("chart_revision", "")).lower()
        lifecycle_commit = str(value.get("lifecycle_reference_commit", "")).lower()
        if "@sha256:" not in resolved_image or "@sha256:" not in sidecar_image:
            raise ValueError("srsRAN configured runtime images are not immutable digest references")
        if not _GIT_SHA_RE.fullmatch(chart_revision) or not _GIT_SHA_RE.fullmatch(lifecycle_commit):
            raise ValueError("srsRAN runtime provenance does not contain immutable source revisions")
        result["srsran"] = {
            "chart_repository": value.get("chart_repository"),
            "chart_revision": chart_revision,
            "configured_image": resolved_image,
            "log_sidecar_image": sidecar_image,
            "lifecycle_reference_repository": value.get("lifecycle_reference_repository"),
            "lifecycle_reference_commit": lifecycle_commit,
        }
        if platform == "rfsim":
            ue_value = _json_object(
                run_dir / "provenance/srsran-rfsim-ue-runtime.json",
                "srsRAN RFSIM UE runtime provenance",
            )
            configured = str(ue_value.get("configured_image", ""))
            live_image_id = str(ue_value.get("live_image_id", ""))
            if "@sha256:" not in configured or _DIGEST_RE.search(live_image_id) is None:
                raise ValueError("srsRAN RFSIM UE image identity is incomplete")
            result["srsran_rfsim_ue"] = {
                "configured_image": configured,
                "runtime_image_id": live_image_id,
                "pod_spec_image": ue_value.get("pod_spec_image"),
            }
    return result


def build_implementation_identity(
    candidate: dict[str, Any], run_dir: str | Path
) -> dict[str, Any]:
    deployment = candidate.get("deployment")
    if not isinstance(deployment, dict):
        raise ValueError("candidate deployment identity has no deployment mapping")
    run_dir = Path(run_dir).resolve()
    return {
        "schema_version": 1,
        "reviewed_sources": selected_source_pins(deployment, run_dir),
        "selected_adapter": selected_adapter_identity(deployment),
        "selected_runtime": selected_runtime_refs(deployment, run_dir),
        "cluster_runtime": selected_cluster_runtime_identity(deployment, run_dir),
    }
