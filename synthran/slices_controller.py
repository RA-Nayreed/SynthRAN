"""Read-only verification of the SLICES CLI controller boundary."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import platform
import re
import shutil
import subprocess
from typing import Any, Callable, Mapping, Sequence

from synthran.dependencies import DependencyLock


SLICES_CONTROLLER_SCHEMA = "synthran/slices-controller/v1alpha1"
EXPECTED_POS_VERSION = "2.5.35"
SAFE_CONTEXT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
VERSION_RE = re.compile(r"(?<![0-9])([0-9]+\.[0-9]+(?:\.[0-9]+)?)(?![0-9])")
DEFAULT_CONTROLLER_TIMEOUT_SECONDS = 60


class SlicesControllerError(RuntimeError):
    """Raised when the active shell is not a verified SLICES controller."""


@dataclass(frozen=True)
class ControllerCommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


@dataclass(frozen=True)
class SlicesControllerReport:
    dependency_lock_sha256: str
    project_fingerprint: str
    experiment_fingerprint: str
    python_version: str
    ansible_version: str
    pos_version: str
    slices_cli_version: str

    @property
    def ready(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SLICES_CONTROLLER_SCHEMA,
            "ready": True,
            "dependency_lock_sha256": self.dependency_lock_sha256,
            "project_fingerprint": self.project_fingerprint,
            "experiment_fingerprint": self.experiment_fingerprint,
            "python_version": self.python_version,
            "ansible_version": self.ansible_version,
            "pos_version": self.pos_version,
            "slices_cli_version": self.slices_cli_version,
        }

    def render(self) -> str:
        return "\n".join(
            (
                "SynthRAN SLICES controller doctor (read-only)",
                "[PASS] platform: Linux controller",
                "[PASS] environment: active synthran Conda environment",
                f"[PASS] Python: exact locked version {self.python_version}",
                f"[PASS] Ansible: exact locked version {self.ansible_version}",
                f"[PASS] POS: exact supported version {self.pos_version}",
                f"[PASS] SLICES CLI: authenticated version {self.slices_cli_version}",
                "[PASS] context: selected project and existing experiment verified",
                "Result: READY",
            )
        )


Runner = Callable[[Sequence[str], int], ControllerCommandResult]
Which = Callable[[str], str | None]


def subprocess_runner(
    command: Sequence[str], timeout_seconds: int
) -> ControllerCommandResult:
    """Run one read-only controller probe without a shell."""

    try:
        completed = subprocess.run(
            list(command),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise SlicesControllerError("a required controller executable was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise SlicesControllerError("a SLICES controller probe timed out") from exc
    return ControllerCommandResult(
        completed.returncode, completed.stdout, completed.stderr
    )


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def dependency_lock_sha256(lock: DependencyLock) -> str:
    try:
        content = lock.path.read_bytes()
    except OSError as exc:
        raise SlicesControllerError("dependency lock cannot be fingerprinted") from exc
    return hashlib.sha256(content).hexdigest()


def validate_context(value: str, label: str) -> str:
    if not SAFE_CONTEXT_RE.fullmatch(value):
        raise SlicesControllerError(
            f"{label} must contain only letters, numbers, '.', '_', ':', or '-'"
        )
    return value


def _locked_conda_version(lock: DependencyLock, package: str) -> str:
    conda = lock.raw.get("conda")
    packages = conda.get("packages") if isinstance(conda, dict) else None
    entry = packages.get(package) if isinstance(packages, dict) else None
    version = entry.get("version") if isinstance(entry, dict) else None
    if not isinstance(version, str) or not version:
        raise SlicesControllerError(
            f"dependency lock does not define conda package {package}"
        )
    return version


def _checked_output(
    runner: Runner,
    command: Sequence[str],
    *,
    timeout_seconds: int,
    label: str,
) -> str:
    try:
        result = runner(command, timeout_seconds)
    except SlicesControllerError as exc:
        raise SlicesControllerError(f"{label} failed: {exc}") from exc
    if result.returncode != 0:
        raise SlicesControllerError(f"{label} failed")
    output = result.stdout.strip()
    if not output:
        raise SlicesControllerError(f"{label} returned no output")
    return output


def _version(output: str, label: str) -> str:
    match = VERSION_RE.search(output)
    if match is None:
        raise SlicesControllerError(f"{label} did not report a parseable version")
    return match.group(1)


def _contains_context(output: str, expected: str, label: str) -> None:
    alphabet = r"A-Za-z0-9._:-"
    pattern = re.compile(
        rf"(?<![{alphabet}]){re.escape(expected)}(?![{alphabet}])"
    )
    if pattern.search(output) is None:
        raise SlicesControllerError(f"active SLICES {label} does not match the request")


def verify_slices_controller(
    *,
    lock: DependencyLock,
    project: str,
    experiment: str,
    runner: Runner = subprocess_runner,
    which: Which = shutil.which,
    environment: Mapping[str, str] | None = None,
    system_name: str | None = None,
    python_version: str | None = None,
    timeout_seconds: int = DEFAULT_CONTROLLER_TIMEOUT_SECONDS,
) -> SlicesControllerReport:
    """Verify the supported Linux SLICES CLI context without changing it."""

    project = validate_context(project, "SLICES project")
    experiment = validate_context(experiment, "SLICES experiment")
    if timeout_seconds <= 0 or timeout_seconds > 300:
        raise SlicesControllerError("controller timeout must be between 1 and 300 seconds")
    if (system_name or platform.system()) != "Linux":
        raise SlicesControllerError("live operation requires a Linux SLICES controller")
    active_environment = (environment or os.environ).get("CONDA_DEFAULT_ENV")
    if active_environment != "synthran":
        raise SlicesControllerError(
            "live operation requires the active Conda environment 'synthran'"
        )

    expected_python = _locked_conda_version(lock, "python")
    observed_python = python_version or platform.python_version()
    if observed_python != expected_python:
        raise SlicesControllerError(
            f"controller Python must exactly match locked version {expected_python}"
        )

    required_tools = (
        "slices",
        "pos",
        "git",
        "ssh",
        "ansible-playbook",
        "ansible-galaxy",
    )
    missing = tuple(name for name in required_tools if which(name) is None)
    if missing:
        raise SlicesControllerError(
            "missing required controller command(s): " + ", ".join(missing)
        )

    expected_ansible = _locked_conda_version(lock, "ansible-core")
    ansible_version = _version(
        _checked_output(
            runner,
            ("ansible-playbook", "--version"),
            timeout_seconds=timeout_seconds,
            label="Ansible controller probe",
        ),
        "Ansible controller probe",
    )
    if ansible_version != expected_ansible:
        raise SlicesControllerError(
            f"ansible-core must exactly match locked version {expected_ansible}"
        )
    _checked_output(
        runner,
        ("ansible-galaxy", "--version"),
        timeout_seconds=timeout_seconds,
        label="ansible-galaxy probe",
    )

    pos_version = _version(
        _checked_output(
            runner,
            ("pos", "--version"),
            timeout_seconds=timeout_seconds,
            label="POS version probe",
        ),
        "POS version probe",
    )
    if pos_version != EXPECTED_POS_VERSION:
        raise SlicesControllerError(
            f"POS must exactly match supported version {EXPECTED_POS_VERSION}"
        )
    slices_version = _version(
        _checked_output(
            runner,
            ("slices", "--version"),
            timeout_seconds=timeout_seconds,
            label="SLICES CLI version probe",
        ),
        "SLICES CLI version probe",
    )
    _checked_output(
        runner,
        ("slices", "auth", "show"),
        timeout_seconds=timeout_seconds,
        label="SLICES authentication probe",
    )
    project_output = _checked_output(
        runner,
        ("slices", "project", "show"),
        timeout_seconds=timeout_seconds,
        label="SLICES project probe",
    )
    _contains_context(project_output, project, "project")
    experiment_output = _checked_output(
        runner,
        ("slices", "experiment", "show", experiment),
        timeout_seconds=timeout_seconds,
        label="SLICES experiment probe",
    )
    _contains_context(experiment_output, experiment, "experiment")

    return SlicesControllerReport(
        dependency_lock_sha256=dependency_lock_sha256(lock),
        project_fingerprint=fingerprint(project),
        experiment_fingerprint=fingerprint(experiment),
        python_version=observed_python,
        ansible_version=ansible_version,
        pos_version=pos_version,
        slices_cli_version=slices_version,
    )
