"""Read-only SLICES experiment discovery for the durable workspace project."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from synthran.workspace.access import ProbeResult, Runner, subprocess_runner
from synthran.workspace.model import WorkspaceError, validate_safe_name
from synthran.workspace.session import verify_slices_experiment_binding


PROVIDER_READ_TIMEOUT_SECONDS = 60
TABLE_CELL_RE = re.compile(r"^\s*│(?P<body>.*)│\s*$")
NO_EXPERIMENTS_MARKERS = (
    "no experiments",
    "no experiment found",
    "no experiments found",
)


@dataclass(frozen=True)
class ProviderExperimentChoice:
    name: str


def parse_slices_experiment_list(output: str) -> tuple[ProviderExperimentChoice, ...]:
    """Extract experiment names only from the first column of a SLICES table."""

    lower = output.lower()
    if any(marker in lower for marker in NO_EXPERIMENTS_MARKERS):
        return ()

    names: list[str] = []
    for line in output.splitlines():
        match = TABLE_CELL_RE.match(line)
        if match is None:
            continue
        cells = [cell.strip() for cell in match.group("body").split("│")]
        if not cells:
            continue
        candidate = cells[0]
        if not candidate or candidate.lower() in {"name", "experiment", "experiments"}:
            continue
        try:
            validate_safe_name(candidate, "SLICES experiment")
        except WorkspaceError:
            continue
        if candidate not in names:
            names.append(candidate)

    if not names:
        raise WorkspaceError("SLICES experiment list output could not be recognized safely")
    return tuple(ProviderExperimentChoice(name=name) for name in names)


def discover_slices_experiments(
    *,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = PROVIDER_READ_TIMEOUT_SECONDS,
) -> tuple[ProviderExperimentChoice, ...]:
    """List SLICES experiment names from the currently verified project context."""

    result: ProbeResult = runner(("slices", "experiment", "list"), timeout_seconds)
    if result.returncode != 0:
        raise WorkspaceError("SLICES experiments could not be listed")
    output = "\n".join((result.stdout, result.stderr)).strip()
    return parse_slices_experiment_list(output)


def verified_slices_experiment(
    name: str,
    *,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = PROVIDER_READ_TIMEOUT_SECONDS,
) -> str:
    """Return an exact SLICES experiment name only after a successful provider check."""

    validate_safe_name(name, "SLICES experiment")
    observation = verify_slices_experiment_binding(
        experiment=name,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    if not observation.usable:
        raise WorkspaceError("selected SLICES experiment is not active")
    return observation.experiment
