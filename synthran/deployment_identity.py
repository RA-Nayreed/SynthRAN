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
_EXECUTION_MANIFEST_SCHEMA = 1
_REFERENCE_REPO_PATH = "third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json"


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


def _files(entries: Iterable[Path]) -> list[Path]:
    result: set[Path] = set()
    for entry in entries:
        if entry.is_file():
            result.add(entry.resolve())
        elif entry.is_dir():
            for path in entry.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    result.add(path.resolve())
    return sorted(result)


def _selected_staged_entries(deployment: dict[str, Any], staged_root: Path) -> list[Path]:
    core = str(deployment.get("core", "")).lower()
    ran = str(deployment.get("ran", "")).lower()
    platform = str(deployment.get("platform", "")).lower()
    ran_path = "srsRAN" if ran == "srsran" else ran
    entries = [
        staged_root / "playbooks",
        staged_root / "group_vars/all/all.yml",
        staged_root / "roles/setup",
        staged_root / "roles/5g" / core,
        staged_root / "roles/5g" / ran_path,
        staged_root / "scripts/collect_cluster_snapshot.py",
        staged_root / "reference/EXECUTION_REFERENCE.json",
    ]
    if platform == "r2lab":
        entries.extend(
            [
                staged_root / "roles/r2lab",
                staged_root / "roles/synthran/r2lab_ue_verify",
                staged_root / "scripts/probe_r2lab_ue.py",
                staged_root / "scripts/secure_ssh_wrapper.py",
            ]
        )
    elif platform == "rfsim":
        entries.append(staged_root / "scripts/probe_software_ues.py")
    return entries


def _repository_path(staged_root: Path, path: Path) -> str:
    relative = path.relative_to(staged_root)
    if relative.parts[0] == "reference":
        return _REFERENCE_REPO_PATH
    return str(Path("deployment") / relative)


def _staged_path(staged_root: Path, repository_path: str) -> Path:
    if repository_path == _REFERENCE_REPO_PATH:
        return staged_root / "reference/EXECUTION_REFERENCE.json"
    prefix = "deployment/"
    if not repository_path.startswith(prefix):
        raise ValueError(
            f"staged execution manifest contains unsupported repository path {repository_path!r}"
        )
    return staged_root / repository_path[len(prefix) :]


def build_execution_manifest(
    deployment: dict[str, Any], staged_root: str | Path
) -> dict[str, Any]:
    """Describe the exact selected Ansible inputs staged for this run."""

    staged_root = Path(staged_root).resolve()
    files = _files(_selected_staged_entries(deployment, staged_root))
    if not files:
        raise ValueError("selected staged execution context contains no files")
    records = [
        {"path": _repository_path(staged_root, path), "sha256": _sha256_file(path)}
        for path in files
    ]
    return {
        "schema_version": _EXECUTION_MANIFEST_SCHEMA,
        "file_count": len(records),
        "sha256": content_hash(records),
        "files": records,
    }


def write_execution_manifest(
    deployment: dict[str, Any], staged_root: str | Path, output: str | Path
) -> dict[str, Any]:
    manifest = build_execution_manifest(deployment, staged_root)
    output = Path(output)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _execution_manifest(run_dir: Path) -> dict[str, Any]:
    value = _json_object(run_dir / "execution-manifest.json", "staged execution manifest")
    files = value.get("files")
    if value.get("schema_version") != _EXECUTION_MANIFEST_SCHEMA or not isinstance(files, list):
        raise ValueError("staged execution manifest schema is unsupported")
    if value.get("file_count") != len(files) or value.get("sha256") != content_hash(files):
        raise ValueError("staged execution manifest failed its integrity check")
    return value


def _validate_records(manifest: dict[str, Any], resolve_path) -> None:
    for record in manifest["files"]:
        if not isinstance(record, dict):
            raise ValueError("staged execution manifest contains a malformed file record")
        relative = str(record.get("path", ""))
        expected = str(record.get("sha256", ""))
        path = resolve_path(relative)
        if not path.is_file() or _sha256_file(path) != expected:
            raise ValueError(
                f"deployment input {relative!r} differs from the accepted staged execution context"
            )


def validate_current_execution_inputs(manifest: dict[str, Any]) -> None:
    """Reject reuse when a repository file actually staged for the run changed."""

    def current_path(relative: str) -> Path:
        path = (ROOT / relative).resolve()
        try:
            path.relative_to(ROOT)
        except ValueError as exc:
            raise ValueError(
                "staged execution manifest contains a path outside the repository"
            ) from exc
        return path

    _validate_records(manifest, current_path)


def validate_staged_execution_inputs(
    manifest: dict[str, Any], staged_root: str | Path
) -> None:
    """Reject reuse when the retained private execution context was altered."""

    staged_root = Path(staged_root).resolve()

    def staged_path(relative: str) -> Path:
        path = _staged_path(staged_root, relative).resolve()
        try:
            path.relative_to(staged_root)
        except ValueError as exc:
            raise ValueError(
                "staged execution manifest resolves outside the private execution context"
            ) from exc
        return path

    _validate_records(manifest, staged_path)


def execution_reference() -> dict[str, str]:
    value = _json_object(
        ROOT / _REFERENCE_REPO_PATH,
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


def validate_current_implementation_inputs(
    identity: dict[str, Any], run_dir: str | Path
) -> None:
    deployment = identity.get("deployment")
    implementation = identity.get("implementation")
    if not isinstance(deployment, dict) or not isinstance(implementation, dict):
        raise ValueError("accepted deployment identity is missing implementation inputs")
    run_dir = Path(run_dir).resolve()
    manifest = _execution_manifest(run_dir)
    if manifest.get("sha256") != implementation.get("execution_context", {}).get("sha256"):
        raise ValueError("accepted execution manifest differs from the sealed implementation identity")
    validate_current_execution_inputs(manifest)
    if selected_source_pins(deployment, run_dir) != implementation.get("reviewed_sources"):
        raise ValueError(
            "current immutable deployment source pins differ from the accepted-testbed identity; redeploy before reuse"
        )


def validate_retained_execution_context(
    identity: dict[str, Any], run_dir: str | Path, private_dir: str | Path
) -> None:
    implementation = identity.get("implementation")
    if not isinstance(implementation, dict):
        raise ValueError("accepted deployment identity is missing implementation inputs")
    manifest = _execution_manifest(Path(run_dir).resolve())
    if manifest.get("sha256") != implementation.get("execution_context", {}).get("sha256"):
        raise ValueError("accepted execution manifest differs from the sealed implementation identity")
    validate_staged_execution_inputs(manifest, Path(private_dir).resolve() / "ansible")


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
    execution = _execution_manifest(run_dir)
    validate_current_execution_inputs(execution)
    return {
        "schema_version": 2,
        "execution_context": {
            "sha256": execution["sha256"],
            "file_count": execution["file_count"],
        },
        "reviewed_sources": selected_source_pins(deployment, run_dir),
        "selected_runtime": selected_runtime_refs(deployment, run_dir),
        "cluster_runtime": selected_cluster_runtime_identity(deployment, run_dir),
    }
