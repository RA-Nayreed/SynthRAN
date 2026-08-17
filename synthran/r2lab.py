"""Fail-closed R2Lab resource control through the Faraday gateway."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Callable, Mapping, Sequence, TextIO

from synthran.live_preflight import CommandResult
from synthran.network.runtime import validate_run_id


R2LAB_GATEWAY = "faraday.inria.fr"
R2LAB_SCHEMA = "synthran/r2lab-resource/v1alpha1"
R2LAB_PLAN_SCHEMA = "synthran/r2lab-plan/v1alpha1"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_REACHABILITY_ATTEMPTS = 12
DEFAULT_REACHABILITY_DELAY_SECONDS = 10.0
DEFAULT_POWER_SETTLE_SECONDS = 20.0

SUPPORTED_RADIOS = frozenset({"n300", "n320"})
SUPPORTED_QHATS = frozenset(
    {
        "qhat01",
        "qhat02",
        "qhat03",
        "qhat10",
        "qhat11",
        "qhat20",
        "qhat21",
        "qhat22",
    }
)
SUPPORTED_QFITS = frozenset(
    {"qfit07", "qfit09", "qfit18", "qfit29", "qfit32", "qfit34"}
)
QMI_QHATS = frozenset({"qhat20", "qhat21", "qhat22"})


class R2LabResourceError(RuntimeError):
    """Raised when R2Lab authority or selected-resource state is unsafe."""


Runner = Callable[[Sequence[str], int], CommandResult]
Sleeper = Callable[[float], None]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_slice(value: str) -> str:
    if not value or len(value) > 64:
        raise R2LabResourceError("R2Lab slice name must contain 1-64 safe characters")
    if any(not (character.isalnum() or character in "._-") for character in value):
        raise R2LabResourceError(
            "R2Lab slice name may contain only letters, numbers, '.', '_', or '-'"
        )
    return value


def _validate_radio(value: str) -> str:
    radio = value.strip().lower()
    if radio not in SUPPORTED_RADIOS:
        supported = ", ".join(sorted(SUPPORTED_RADIOS))
        raise R2LabResourceError(f"unsupported R2Lab radio; choose one of: {supported}")
    return radio


def _validate_ue(value: str) -> str:
    ue = value.strip().lower()
    if ue not in SUPPORTED_QHATS and ue not in SUPPORTED_QFITS:
        supported = ", ".join(sorted(SUPPORTED_QHATS | SUPPORTED_QFITS))
        raise R2LabResourceError(f"unsupported R2Lab UE; choose one of: {supported}")
    return ue


def _ue_kind(ue: str) -> str:
    return "qhat" if ue in SUPPORTED_QHATS else "qfit"


def _ue_mode(ue: str) -> str:
    return "qmi" if ue in QMI_QHATS else "mbim"


def _validate_timeout(value: int) -> int:
    if value < 5 or value > 300:
        raise R2LabResourceError("R2Lab command timeout must be between 5 and 300 seconds")
    return value


def _validate_run(value: str) -> str:
    try:
        run_id = validate_run_id(value)
    except Exception as exc:
        raise R2LabResourceError(str(exc)) from exc
    if run_id == "active":
        raise R2LabResourceError("run ID 'active' is reserved by the R2Lab provider")
    return run_id


def subprocess_runner(command: Sequence[str], timeout_seconds: int) -> CommandResult:
    """Execute one argv-only local command and capture its result."""

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
        raise R2LabResourceError("ssh is required for R2Lab control") from exc
    except subprocess.TimeoutExpired as exc:
        raise R2LabResourceError("R2Lab command timed out") from exc
    return CommandResult(completed.returncode, completed.stdout or "", completed.stderr or "")


def gateway_command(slice_name: str, *remote: str) -> tuple[str, ...]:
    """Build the strict public-key SSH boundary used for all gateway actions."""

    slice_name = _validate_slice(slice_name)
    return (
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=yes",
        "--",
        f"{slice_name}@{R2LAB_GATEWAY}",
        *remote,
    )


@dataclass(frozen=True)
class R2LabSelection:
    """One exact physical-radio resource selection."""

    slice_name: str
    radio: str
    ue: str

    @classmethod
    def build(cls, *, slice_name: str, radio: str, ue: str) -> "R2LabSelection":
        return cls(
            slice_name=_validate_slice(slice_name),
            radio=_validate_radio(radio),
            ue=_validate_ue(ue),
        )

    @property
    def ue_kind(self) -> str:
        return _ue_kind(self.ue)

    @property
    def ue_mode(self) -> str:
        return _ue_mode(self.ue)

    @property
    def slice_fingerprint(self) -> str:
        return _fingerprint(self.slice_name)

    def public_summary(self) -> dict[str, str]:
        return {
            "gateway": R2LAB_GATEWAY,
            "slice_fingerprint": self.slice_fingerprint,
            "radio": self.radio,
            "ue": self.ue,
            "ue_kind": self.ue_kind,
            "ue_mode": self.ue_mode,
        }


@dataclass(frozen=True)
class R2LabPlan:
    run_id: str
    selection: R2LabSelection

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": R2LAB_PLAN_SCHEMA,
            "execution_enabled": False,
            "run_id": self.run_id,
            "lease_action": "reuse-active",
            "resources": self.selection.public_summary(),
            "commands": [
                "ssh <r2lab-slice>@faraday.inria.fr rhubarbe leases --check",
                f"ssh <r2lab-slice>@faraday.inria.fr rhubarbe pdu on {self.selection.radio}",
                (
                    f"ssh <r2lab-slice>@faraday.inria.fr rhubarbe pdu off {self.selection.ue}"
                    if self.selection.ue_kind == "qhat"
                    else f"ssh <r2lab-slice>@faraday.inria.fr qfit off {self.selection.ue}"
                ),
                (
                    f"ssh <r2lab-slice>@faraday.inria.fr rhubarbe pdu on {self.selection.ue}"
                    if self.selection.ue_kind == "qhat"
                    else f"ssh <r2lab-slice>@faraday.inria.fr qfit on {self.selection.ue}"
                ),
                f"ssh <r2lab-slice>@faraday.inria.fr ping -c 1 -W 1 {self.selection.ue}",
            ],
            "safety": {
                "global_power_off": False,
                "password_storage": False,
                "automatic_lease_booking": False,
                "one_active_selection_per_workspace": True,
            },
        }

    def render(self, *, as_json: bool = False) -> str:
        payload = self.to_dict()
        if as_json:
            return json.dumps(payload, indent=2, sort_keys=True)
        resources = payload["resources"]
        assert isinstance(resources, dict)
        return "\n".join(
            (
                "SynthRAN R2Lab resource plan (NON-EXECUTING)",
                f"Run ID: {self.run_id}",
                f"Radio: {resources['radio']}",
                f"UE: {resources['ue']} ({resources['ue_kind']}, {resources['ue_mode']})",
                "Lease: require and reuse the active R2Lab lease",
                "Credentials: SSH key only; no R2Lab password is stored",
                "Cleanup: exact selected radio and UE only; global power-off is forbidden",
            )
        )


def build_plan(*, run_id: str, selection: R2LabSelection) -> R2LabPlan:
    return R2LabPlan(run_id=_validate_run(run_id), selection=selection)


@dataclass(frozen=True)
class R2LabCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class R2LabDoctorReport:
    selection: R2LabSelection
    checks: tuple[R2LabCheck, ...]

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def render(self) -> str:
        lines = ["SynthRAN R2Lab doctor (read-only)"]
        for check in self.checks:
            lines.append(
                f"[{'PASS' if check.passed else 'FAIL'}] {check.name}: {check.detail}"
            )
        lines.append(f"Result: {'READY' if self.ready else 'NOT READY'}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "synthran/r2lab-doctor/v1alpha1",
            "ready": self.ready,
            "resources": self.selection.public_summary(),
            "checks": [
                {"name": check.name, "passed": check.passed, "detail": check.detail}
                for check in self.checks
            ],
        }


def run_doctor(
    *,
    selection: R2LabSelection,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> R2LabDoctorReport:
    """Verify gateway access and an active owned lease without mutation."""

    timeout_seconds = _validate_timeout(timeout_seconds)
    checks: list[R2LabCheck] = [
        R2LabCheck(
            "selection",
            True,
            f"supported {selection.radio} + {selection.ue} resource pair",
        )
    ]

    gateway = runner(gateway_command(selection.slice_name, "true"), timeout_seconds)
    gateway_ok = gateway.returncode == 0
    checks.append(
        R2LabCheck(
            "gateway",
            gateway_ok,
            "strict public-key SSH to Faraday succeeded"
            if gateway_ok
            else "strict public-key SSH to Faraday failed",
        )
    )
    if not gateway_ok:
        return R2LabDoctorReport(selection, tuple(checks))

    lease = runner(
        gateway_command(selection.slice_name, "rhubarbe", "leases", "--check"),
        timeout_seconds,
    )
    lease_ok = lease.returncode == 0
    checks.append(
        R2LabCheck(
            "lease",
            lease_ok,
            "active R2Lab lease verified"
            if lease_ok
            else "no active R2Lab lease could be verified",
        )
    )
    return R2LabDoctorReport(selection, tuple(checks))


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def _manifest_payload(
    *,
    run_id: str,
    selection: R2LabSelection,
    status: str,
    updated_at: datetime,
    claim_held: bool,
    failure_stage: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": R2LAB_SCHEMA,
        "run_id": run_id,
        "status": status,
        "updated_at_utc": _format_time(updated_at),
        "lease_action": "reuse-active",
        "resources": selection.public_summary(),
        "resource_claim": "held" if claim_held else "released",
        "password_storage": False,
        "global_power_off": False,
    }
    if failure_stage is not None:
        payload["failure_stage"] = failure_stage
    return payload


def _load_json(path: Path, label: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise R2LabResourceError(f"{label} was not found") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R2LabResourceError(f"{label} must be readable JSON") from exc
    if not isinstance(payload, dict):
        raise R2LabResourceError(f"{label} must contain one JSON object")
    return payload


def _selection_from_manifest(
    payload: Mapping[str, object], *, slice_name: str, run_id: str
) -> R2LabSelection:
    if payload.get("schema") != R2LAB_SCHEMA or payload.get("run_id") != run_id:
        raise R2LabResourceError("R2Lab manifest does not match the requested run")
    resources = payload.get("resources")
    if not isinstance(resources, dict):
        raise R2LabResourceError("R2Lab manifest resource selection is malformed")
    fingerprint = resources.get("slice_fingerprint")
    if fingerprint != _fingerprint(_validate_slice(slice_name)):
        raise R2LabResourceError("R2Lab slice authority does not match the run manifest")
    radio = resources.get("radio")
    ue = resources.get("ue")
    if not isinstance(radio, str) or not isinstance(ue, str):
        raise R2LabResourceError("R2Lab manifest resource selection is incomplete")
    return R2LabSelection.build(slice_name=slice_name, radio=radio, ue=ue)


def _claim_path(run_root: Path) -> Path:
    return run_root.resolve() / "active.json"


def _write_claim(path: Path, *, run_id: str, selection: R2LabSelection) -> None:
    if path.exists():
        raise R2LabResourceError(
            "another R2Lab resource claim exists in this workspace; release or inspect it first"
        )
    payload = {
        "schema": "synthran/r2lab-claim/v1alpha1",
        "run_id": run_id,
        "slice_fingerprint": selection.slice_fingerprint,
        "radio": selection.radio,
        "ue": selection.ue,
        "created_at_utc": _format_time(_utc_now()),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise R2LabResourceError(
            "another R2Lab resource claim appeared concurrently"
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError:
        path.unlink(missing_ok=True)
        raise


def _require_claim(path: Path, *, run_id: str, selection: R2LabSelection) -> None:
    payload = _load_json(path, "active R2Lab resource claim")
    expected = {
        "schema": "synthran/r2lab-claim/v1alpha1",
        "run_id": run_id,
        "slice_fingerprint": selection.slice_fingerprint,
        "radio": selection.radio,
        "ue": selection.ue,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise R2LabResourceError(
                "active R2Lab resource claim does not match the requested run"
            )


@dataclass(frozen=True)
class R2LabResult:
    run_id: str
    run_directory: Path
    manifest_path: Path
    log_path: Path
    status: str


def execute_prepare(
    *,
    plan: R2LabPlan,
    run_root: Path = Path(".synthran/r2lab"),
    runner: Runner = subprocess_runner,
    sleeper: Sleeper = time.sleep,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    power_settle_seconds: float = DEFAULT_POWER_SETTLE_SECONDS,
    reachability_attempts: int = DEFAULT_REACHABILITY_ATTEMPTS,
    reachability_delay_seconds: float = DEFAULT_REACHABILITY_DELAY_SECONDS,
    progress: TextIO | None = None,
) -> R2LabResult:
    """Claim and power exactly one R2Lab radio/UE pair under an active lease."""

    timeout_seconds = _validate_timeout(timeout_seconds)
    if power_settle_seconds < 0 or reachability_delay_seconds < 0:
        raise R2LabResourceError("R2Lab wait intervals must not be negative")
    if reachability_attempts < 1 or reachability_attempts > 60:
        raise R2LabResourceError("R2Lab reachability attempts must be between 1 and 60")

    run_root = run_root.resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    run_directory = run_root / plan.run_id
    try:
        run_directory.mkdir()
    except FileExistsError as exc:
        raise R2LabResourceError(
            "R2Lab run directory already exists; choose a new run ID"
        ) from exc

    manifest_path = run_directory / "manifest.json"
    log_path = run_directory / "r2lab.log"
    claim_path = _claim_path(run_root)
    log_lines: list[str] = []
    claim_held = False

    def report(message: str) -> None:
        if progress is not None:
            print(f"[synthran] {message}", file=progress, flush=True)

    def write_manifest(status: str, failure_stage: str | None = None) -> None:
        _atomic_json(
            manifest_path,
            _manifest_payload(
                run_id=plan.run_id,
                selection=plan.selection,
                status=status,
                updated_at=_utc_now(),
                claim_held=claim_held,
                failure_stage=failure_stage,
            ),
        )

    def finish_log() -> None:
        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    def fail(stage: str, message: str) -> None:
        log_lines.append(f"{stage}: FAIL - {message}")
        write_manifest("failed", stage)
        finish_log()

    def remote(stage: str, *command: str) -> CommandResult:
        report(f"{stage}: running...")
        result = runner(gateway_command(plan.selection.slice_name, *command), timeout_seconds)
        if result.returncode != 0:
            report(f"{stage}: FAILED")
            fail(stage, "gateway command returned nonzero")
            raise R2LabResourceError(
                f"R2Lab stage {stage} failed; see the sanitized run log"
            )
        log_lines.append(f"{stage}: OK")
        report(f"{stage}: OK")
        return result

    def require_lease(stage: str) -> None:
        remote(stage, "rhubarbe", "leases", "--check")

    write_manifest("running")
    require_lease("lease-check")
    try:
        _write_claim(claim_path, run_id=plan.run_id, selection=plan.selection)
    except (OSError, R2LabResourceError) as exc:
        fail("resource-claim", "unable to acquire the workspace resource claim")
        raise R2LabResourceError("unable to claim R2Lab resources safely") from exc
    claim_held = True
    write_manifest("running")
    log_lines.append("resource-claim: OK")

    require_lease("lease-before-radio")
    remote("radio-power-on", "rhubarbe", "pdu", "on", plan.selection.radio)

    require_lease("lease-before-ue-off")
    if plan.selection.ue_kind == "qhat":
        remote("ue-power-off", "rhubarbe", "pdu", "off", plan.selection.ue)
    else:
        remote("ue-power-off", "qfit", "off", plan.selection.ue)

    sleeper(power_settle_seconds)
    require_lease("lease-before-ue-on")
    if plan.selection.ue_kind == "qhat":
        remote("ue-power-on", "rhubarbe", "pdu", "on", plan.selection.ue)
    else:
        remote("ue-power-on", "qfit", "on", plan.selection.ue)

    report("ue-reachability: running...")
    reachable = False
    for attempt in range(1, reachability_attempts + 1):
        probe = runner(
            gateway_command(
                plan.selection.slice_name,
                "ping",
                "-c",
                "1",
                "-W",
                "1",
                plan.selection.ue,
            ),
            timeout_seconds,
        )
        if probe.returncode == 0:
            reachable = True
            log_lines.append(f"ue-reachability: OK on attempt {attempt}")
            report("ue-reachability: OK")
            break
        if attempt < reachability_attempts:
            sleeper(reachability_delay_seconds)
    if not reachable:
        report("ue-reachability: FAILED")
        fail("ue-reachability", "selected UE did not become reachable")
        raise R2LabResourceError("selected R2Lab UE did not become reachable")

    require_lease("lease-final")
    write_manifest("ready")
    finish_log()
    report("R2Lab resources: READY")
    return R2LabResult(
        plan.run_id,
        run_directory,
        manifest_path,
        log_path,
        "ready",
    )


def execute_release(
    *,
    run_id: str,
    slice_name: str,
    run_root: Path = Path(".synthran/r2lab"),
    runner: Runner = subprocess_runner,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    progress: TextIO | None = None,
) -> R2LabResult:
    """Power off only the exact resources held by one local SynthRAN claim."""

    run_id = _validate_run(run_id)
    slice_name = _validate_slice(slice_name)
    timeout_seconds = _validate_timeout(timeout_seconds)
    run_root = run_root.resolve()
    run_directory = run_root / run_id
    manifest_path = run_directory / "manifest.json"
    log_path = run_directory / "r2lab.log"
    payload = _load_json(manifest_path, "R2Lab run manifest")
    selection = _selection_from_manifest(payload, slice_name=slice_name, run_id=run_id)
    claim_path = _claim_path(run_root)
    _require_claim(claim_path, run_id=run_id, selection=selection)

    try:
        existing_log = log_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing_log = ""
    except (OSError, UnicodeDecodeError) as exc:
        raise R2LabResourceError("R2Lab run log is not readable") from exc
    log_lines = [line for line in existing_log.splitlines() if line]

    def report(message: str) -> None:
        if progress is not None:
            print(f"[synthran] {message}", file=progress, flush=True)

    def write_manifest(status: str, failure_stage: str | None = None) -> None:
        _atomic_json(
            manifest_path,
            _manifest_payload(
                run_id=run_id,
                selection=selection,
                status=status,
                updated_at=_utc_now(),
                claim_held=claim_path.exists(),
                failure_stage=failure_stage,
            ),
        )

    def finish_log() -> None:
        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    def remote(stage: str, *command: str) -> None:
        report(f"{stage}: running...")
        result = runner(gateway_command(slice_name, *command), timeout_seconds)
        if result.returncode != 0:
            log_lines.append(f"{stage}: FAIL - gateway command returned nonzero")
            write_manifest("release-failed", stage)
            finish_log()
            report(f"{stage}: FAILED")
            raise R2LabResourceError(
                f"R2Lab release stage {stage} failed; resource claim was retained"
            )
        log_lines.append(f"{stage}: OK")
        report(f"{stage}: OK")

    remote("lease-before-release", "rhubarbe", "leases", "--check")
    if selection.ue_kind == "qhat":
        remote("ue-power-off-release", "rhubarbe", "pdu", "off", selection.ue)
    else:
        remote("ue-power-off-release", "qfit", "off", selection.ue)
    remote("lease-before-radio-off", "rhubarbe", "leases", "--check")
    remote("radio-power-off-release", "rhubarbe", "pdu", "off", selection.radio)

    try:
        claim_path.unlink()
    except OSError as exc:
        write_manifest("release-failed", "resource-claim-release")
        finish_log()
        raise R2LabResourceError(
            "resources were powered off but the local R2Lab claim could not be removed"
        ) from exc

    write_manifest("released")
    finish_log()
    report("R2Lab resources: RELEASED")
    return R2LabResult(run_id, run_directory, manifest_path, log_path, "released")


def _selection_from_args(args: argparse.Namespace) -> R2LabSelection:
    if args.slice_name is None:
        raise R2LabResourceError(
            "R2Lab control requires --slice or SYNTHRAN_R2LAB_SLICE"
        )
    return R2LabSelection.build(
        slice_name=args.slice_name,
        radio=args.radio,
        ue=args.ue,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synthran r2lab")
    commands = parser.add_subparsers(dest="r2lab_command", required=True)

    def selection_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--slice",
            dest="slice_name",
            default=os.environ.get("SYNTHRAN_R2LAB_SLICE"),
            help="R2Lab slice name (or SYNTHRAN_R2LAB_SLICE)",
        )
        command.add_argument("--radio", required=True, choices=sorted(SUPPORTED_RADIOS))
        command.add_argument(
            "--ue", required=True, choices=sorted(SUPPORTED_QHATS | SUPPORTED_QFITS)
        )
        command.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)

    doctor = commands.add_parser(
        "doctor", help="verify Faraday access and an active R2Lab lease"
    )
    selection_arguments(doctor)
    doctor.add_argument("--json", action="store_true")

    plan = commands.add_parser(
        "plan", help="render the exact R2Lab resource actions without executing them"
    )
    selection_arguments(plan)
    plan.add_argument("--run-id", required=True)
    plan.add_argument("--json", action="store_true")

    prepare = commands.add_parser(
        "prepare", help="claim and power one R2Lab radio and UE under an active lease"
    )
    selection_arguments(prepare)
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument(
        "--run-root", type=Path, default=Path(".synthran/r2lab"), help=argparse.SUPPRESS
    )

    release = commands.add_parser(
        "release", help="power off only resources owned by one SynthRAN R2Lab run"
    )
    release.add_argument(
        "--slice",
        dest="slice_name",
        default=os.environ.get("SYNTHRAN_R2LAB_SLICE"),
        help="R2Lab slice name (or SYNTHRAN_R2LAB_SLICE)",
    )
    release.add_argument("--run-id", required=True)
    release.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    release.add_argument(
        "--run-root", type=Path, default=Path(".synthran/r2lab"), help=argparse.SUPPRESS
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.r2lab_command == "doctor":
            report = run_doctor(
                selection=_selection_from_args(args), timeout_seconds=args.timeout
            )
            print(
                json.dumps(report.to_dict(), indent=2, sort_keys=True)
                if args.json
                else report.render()
            )
            return 0 if report.ready else 2
        if args.r2lab_command == "plan":
            plan = build_plan(run_id=args.run_id, selection=_selection_from_args(args))
            print(plan.render(as_json=args.json))
            return 0
        if args.r2lab_command == "prepare":
            plan = build_plan(run_id=args.run_id, selection=_selection_from_args(args))
            result = execute_prepare(
                plan=plan,
                run_root=args.run_root,
                timeout_seconds=args.timeout,
                progress=sys.stdout,
            )
            print(f"R2Lab resources prepared for run {result.run_id}.")
            print(f"Sanitized manifest: {result.manifest_path}")
            print(f"Sanitized log: {result.log_path}")
            return 0
        if args.r2lab_command == "release":
            if args.slice_name is None:
                raise R2LabResourceError(
                    "R2Lab release requires --slice or SYNTHRAN_R2LAB_SLICE"
                )
            result = execute_release(
                run_id=args.run_id,
                slice_name=args.slice_name,
                run_root=args.run_root,
                timeout_seconds=args.timeout,
                progress=sys.stdout,
            )
            print(f"R2Lab resources released for run {result.run_id}.")
            print(f"Sanitized manifest: {result.manifest_path}")
            return 0
    except (R2LabResourceError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    raise AssertionError("unreachable R2Lab command")


if __name__ == "__main__":
    raise SystemExit(main())
