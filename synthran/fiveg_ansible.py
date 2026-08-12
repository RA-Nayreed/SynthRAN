"""Safe planning boundary around the pinned ``5g_ansible`` dependency."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Mapping, Sequence

from synthran.dependencies import DependencyError, DependencyLock, load_lock


PLAN_SCHEMA = "synthran/network-plan/v1alpha1"
PROFILE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
SECTION_RE = re.compile(r"^\[([^]]+)]$")
SUPPORTED_CORE = "open5gs"
SUPPORTED_RAN = "srsran"
SUPPORTED_RADIO = "rfsim"


class FiveGAnsibleError(RuntimeError):
    """Raised when an adapter input or locked upstream checkout is unsafe."""


@dataclass(frozen=True)
class InventoryHost:
    """One host entry from an Ansible INI inventory."""

    name: str
    variables: Mapping[str, str]


@dataclass(frozen=True)
class NetworkInventory:
    """The validated subset of inventory facts SynthRAN is allowed to use."""

    path: Path
    sha256: str
    core_node: InventoryHost
    ran_node: InventoryHost
    all_vars: Mapping[str, str]

    @property
    def core(self) -> str:
        return self.all_vars["core"]

    @property
    def ran(self) -> str:
        return self.all_vars["ran"]

    @property
    def radio(self) -> str:
        return self.all_vars["rru"]

    def redacted_summary(self) -> dict[str, Any]:
        """Return reproducibility facts without local paths or host credentials."""

        return {
            "file_name": self.path.name,
            "sha256": self.sha256,
            "core": self.core,
            "ran": self.ran,
            "radio": self.radio,
            "core_node": self.core_node.name,
            "ran_node": self.ran_node.name,
            "co_located": self.core_node.name == self.ran_node.name,
            "monitoring_enabled": False,
        }


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]
    mode: str = "offline"

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def render(self) -> str:
        lines = [f"SynthRAN doctor ({self.mode})"]
        for check in self.checks:
            status = "PASS" if check.passed else "FAIL"
            lines.append(f"[{status}] {check.name}: {check.detail}")
        result = "READY" if self.ready else "NOT READY"
        lines.append(f"Result: {result}")
        return "\n".join(lines)


@dataclass(frozen=True)
class NetworkDeploymentPlan:
    """Redacted, non-executing description of the future deployment operation."""

    inventory: NetworkInventory
    profile: str
    fiveg_ansible_commit: str
    open5gs_k8s_commit: str
    srsran_helm_commit: str

    def commands(self) -> tuple[tuple[str, ...], ...]:
        return (
            (
                "git",
                "-C",
                "<locked-fiveg-checkout>",
                "worktree",
                "add",
                "--detach",
                "<isolated-worktree>",
                self.fiveg_ansible_commit,
            ),
            (
                "ansible-galaxy",
                "collection",
                "install",
                "-r",
                "<isolated-worktree>/.synthran/requirements.yml",
                "-p",
                "<run-collections>",
            ),
            (
                "ansible-playbook",
                "-i",
                "<inventory>",
                "-e",
                f"fiveg_profile={self.profile}",
                "-e",
                f"repo_branch={self.open5gs_k8s_commit}",
                "-e",
                f"version={self.srsran_helm_commit}",
                "-e",
                "ue_count=1",
                "-e",
                "deployment_option=open5gs",
                "<isolated-worktree>/.synthran/golden-path-deploy.yml",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PLAN_SCHEMA,
            "mode": "dry-run",
            "execution_enabled": False,
            "reservation_action": "none",
            "inventory": self.inventory.redacted_summary(),
            "profile": self.profile,
            "dependencies": {
                "fiveg_ansible": self.fiveg_ansible_commit,
                "open5gs_k8s": self.open5gs_k8s_commit,
                "srsran_helm": self.srsran_helm_commit,
            },
            "commands": [list(command) for command in self.commands()],
            "execution_requirements": [
                "fresh matching live preflight evidence",
                "explicit unique run ID",
                "separate ready core and RAN nodes",
                "explicit non-dry-run command",
            ],
        }

    def render(self, *, as_json: bool = False) -> str:
        if as_json:
            return json.dumps(self.to_dict(), indent=2, sort_keys=True)
        summary = self.inventory.redacted_summary()
        lines = [
            "SynthRAN network deployment plan (NON-EXECUTING)",
            f"Inventory: {summary['file_name']} ({summary['sha256'][:12]}...)",
            f"Path: {summary['core']} + {summary['ran']} + {summary['radio']}",
            f"Nodes: core={summary['core_node']} ran={summary['ran_node']}",
            f"Profile: {self.profile}",
            "Reservation action: none",
            "Pinned dependencies:",
            f"  fiveg_ansible={self.fiveg_ansible_commit}",
            f"  open5gs_k8s={self.open5gs_k8s_commit}",
            f"  srsran_helm={self.srsran_helm_commit}",
            "Planned commands:",
        ]
        lines.extend(f"  {shlex.join(command)}" for command in self.commands())
        lines.extend(
            [
                "Live execution: requires fresh matching preflight evidence and a run ID",
                "No reservation, boot, deployment, or experiment command was executed.",
            ]
        )
        return "\n".join(lines)


def _parse_scalar(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise FiveGAnsibleError(f"{label} must not be empty")
    try:
        tokens = shlex.split(value, comments=False, posix=True)
    except ValueError as exc:
        raise FiveGAnsibleError(f"{label} contains invalid quoting") from exc
    if len(tokens) != 1:
        raise FiveGAnsibleError(f"{label} must contain one scalar value")
    return tokens[0]


def _parse_host(line: str, section: str) -> InventoryHost:
    try:
        tokens = shlex.split(line, comments=True, posix=True)
    except ValueError as exc:
        raise FiveGAnsibleError(f"inventory section [{section}] has invalid quoting") from exc
    if not tokens:
        raise FiveGAnsibleError(f"inventory section [{section}] contains an empty host")
    variables: dict[str, str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            raise FiveGAnsibleError(
                f"inventory host variables in [{section}] must use key=value"
            )
        name, value = token.split("=", 1)
        if not name or not value or name in variables:
            raise FiveGAnsibleError(
                f"inventory host variables in [{section}] must be unique and non-empty"
            )
        variables[name] = value
    return InventoryHost(name=tokens[0], variables=variables)


def _require_host_variables(host: InventoryHost, section: str, names: Sequence[str]) -> None:
    missing = [name for name in names if not host.variables.get(name)]
    if missing:
        raise FiveGAnsibleError(
            f"inventory section [{section}] is missing required host variables: "
            + ", ".join(missing)
        )


def _require_false(value: str, label: str) -> None:
    if value.strip().lower() not in {"false", "no", "0"}:
        raise FiveGAnsibleError(f"{label} must be false for the initial golden path")


def parse_inventory(text: str, *, source: Path) -> NetworkInventory:
    """Parse and validate the narrow golden-path Ansible inventory contract."""

    sections: dict[str, list[str]] = {}
    current: str | None = None
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        match = SECTION_RE.fullmatch(line)
        if match:
            current = match.group(1)
            sections.setdefault(current, [])
            continue
        if current is None:
            raise FiveGAnsibleError(
                f"inventory content before the first section at line {number}"
            )
        sections[current].append(line)

    hosts: dict[str, InventoryHost] = {}
    for section in ("core_node", "ran_node"):
        entries = sections.get(section, [])
        if len(entries) != 1:
            raise FiveGAnsibleError(
                f"inventory section [{section}] must contain exactly one host"
            )
        hosts[section] = _parse_host(entries[0], section)

    webshell_entries = sections.get("webshell", [])
    if len(webshell_entries) != 1 or _parse_host(
        webshell_entries[0], "webshell"
    ).name != "localhost":
        raise FiveGAnsibleError("inventory [webshell] must contain localhost exactly once")

    required_children = {
        "sopnodes:children": {"core_node", "ran_node"},
        "k8s_workers:children": {"ran_node"},
    }
    for section, required in required_children.items():
        actual = set(sections.get(section, []))
        if not required.issubset(actual):
            raise FiveGAnsibleError(
                f"inventory [{section}] must include: {', '.join(sorted(required))}"
            )

    all_vars: dict[str, str] = {}
    for line in sections.get("all:vars", []):
        if "=" not in line:
            raise FiveGAnsibleError("inventory [all:vars] entries must use key=value")
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or name in all_vars:
            raise FiveGAnsibleError("inventory [all:vars] names must be unique and non-empty")
        all_vars[name] = _parse_scalar(value, f"inventory variable {name}")

    required_vars = {
        "core",
        "ran",
        "rru",
        "core_node_name",
        "ran_node_name",
        "monitoring_enabled",
    }
    missing_vars = sorted(required_vars.difference(all_vars))
    if missing_vars:
        raise FiveGAnsibleError(
            "inventory [all:vars] is missing required variables: "
            + ", ".join(missing_vars)
        )

    if all_vars["core"].lower() != SUPPORTED_CORE:
        raise FiveGAnsibleError("the golden path supports only core=open5gs")
    if all_vars["ran"].lower() != SUPPORTED_RAN:
        raise FiveGAnsibleError("the golden path supports only ran=srsRAN")
    if all_vars["rru"].lower() != SUPPORTED_RADIO:
        raise FiveGAnsibleError("the golden path supports only rru=rfsim")
    _require_false(all_vars["monitoring_enabled"], "monitoring_enabled")

    core_node = hosts["core_node"]
    ran_node = hosts["ran_node"]
    if all_vars["core_node_name"] != core_node.name:
        raise FiveGAnsibleError("core_node_name must match the [core_node] host")
    if all_vars["ran_node_name"] != ran_node.name:
        raise FiveGAnsibleError("ran_node_name must match the [ran_node] host")
    common_host_variables = ("ansible_user", "nic_interface", "ip", "storage")
    _require_host_variables(core_node, "core_node", common_host_variables)
    _require_host_variables(
        ran_node, "ran_node", (*common_host_variables, "boot_mode")
    )

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return NetworkInventory(
        path=source,
        sha256=digest,
        core_node=core_node,
        ran_node=ran_node,
        all_vars=all_vars,
    )


def load_inventory(path: Path) -> NetworkInventory:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FiveGAnsibleError("inventory file was not found") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise FiveGAnsibleError("inventory file must be readable UTF-8 text") from exc
    return parse_inventory(text, source=path)


def _git_output(args: Sequence[str], *, cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise FiveGAnsibleError("Git is required for dependency validation") from exc
    except subprocess.CalledProcessError as exc:
        raise FiveGAnsibleError("unable to validate the locked fiveg_ansible checkout") from exc
    return completed.stdout.strip()


def validate_fiveg_checkout(lock: DependencyLock, dependency_root: Path) -> Path:
    dependency = next(
        (item for item in lock.git if item.name == "fiveg_ansible"), None
    )
    if dependency is None:
        raise FiveGAnsibleError("dependency lock does not define fiveg_ansible")
    checkout = dependency_root.joinpath(*dependency.checkout.parts)
    if not checkout.is_dir():
        raise FiveGAnsibleError(
            "locked fiveg_ansible checkout is missing; run synthran deps sync"
        )
    if _git_output(("rev-parse", "HEAD"), cwd=checkout) != dependency.commit:
        raise FiveGAnsibleError("fiveg_ansible checkout is not at the locked commit")
    if _git_output(("status", "--porcelain"), cwd=checkout):
        raise FiveGAnsibleError("fiveg_ansible checkout contains local changes")
    if _git_output(("rev-parse", "--abbrev-ref", "HEAD"), cwd=checkout) != "HEAD":
        raise FiveGAnsibleError("fiveg_ansible checkout must be detached")
    if (
        _git_output(("remote", "get-url", "origin"), cwd=checkout).rstrip("/")
        != dependency.url.rstrip("/")
    ):
        raise FiveGAnsibleError("fiveg_ansible checkout origin does not match the lock")
    required_interfaces = (
        "collections/requirements.yml",
        "playbooks/deploy.yml",
        "roles/5g/open5gs/config/defaults/main.yml",
        "roles/5g/srsRAN/common/defaults/main.yml",
    )
    if any(not (checkout / relative).is_file() for relative in required_interfaces):
        raise FiveGAnsibleError("locked fiveg_ansible checkout is missing adapter interfaces")
    return checkout


def run_offline_doctor(
    *, inventory_path: Path, lock_path: Path, dependency_root: Path
) -> DoctorReport:
    checks: list[DoctorCheck] = []
    try:
        inventory = load_inventory(inventory_path)
    except FiveGAnsibleError as exc:
        checks.append(DoctorCheck("inventory", False, str(exc)))
    else:
        checks.append(
            DoctorCheck(
                "inventory",
                True,
                f"{inventory.core} + {inventory.ran} + {inventory.radio}",
            )
        )

    try:
        lock = load_lock(lock_path)
    except DependencyError as exc:
        detail = str(exc)
        if detail.startswith("dependency lock not found:"):
            detail = "dependency lock was not found"
        checks.append(DoctorCheck("dependency-lock", False, detail))
        lock = None
    else:
        checks.append(DoctorCheck("dependency-lock", True, "immutable inputs validated"))

    if lock is not None:
        try:
            validate_fiveg_checkout(lock, dependency_root)
        except FiveGAnsibleError as exc:
            checks.append(DoctorCheck("fiveg-ansible", False, str(exc)))
        else:
            commit = next(
                item.commit for item in lock.git if item.name == "fiveg_ansible"
            )
            checks.append(
                DoctorCheck(
                    "fiveg-ansible",
                    True,
                    f"clean detached checkout at {commit[:12]}",
                )
            )
    return DoctorReport(tuple(checks))


def build_network_plan(
    *, lock: DependencyLock, inventory: NetworkInventory, profile: str
) -> NetworkDeploymentPlan:
    if not PROFILE_RE.fullmatch(profile):
        raise FiveGAnsibleError(
            "fiveg profile may contain only letters, numbers, '_' and '-'"
        )
    git_dependencies = lock.raw.get("git")
    if not isinstance(git_dependencies, dict):
        raise FiveGAnsibleError("dependency lock Git mapping is unavailable")
    try:
        fiveg_commit = git_dependencies["fiveg_ansible"]["commit"]
        open5gs_commit = git_dependencies["open5gs_k8s"]["commit"]
        srsran_commit = git_dependencies["srsran_helm"]["commit"]
    except (KeyError, TypeError) as exc:
        raise FiveGAnsibleError("dependency lock is missing deployment pins") from exc
    return NetworkDeploymentPlan(
        inventory=inventory,
        profile=profile,
        fiveg_ansible_commit=fiveg_commit,
        open5gs_k8s_commit=open5gs_commit,
        srsran_helm_commit=srsran_commit,
    )
