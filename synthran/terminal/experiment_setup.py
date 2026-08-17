"""Local desired-experiment setup for an empty interactive workspace."""

from __future__ import annotations

import os
from typing import Mapping, Protocol, TextIO

from synthran.app.controller import ApplicationController
from synthran.workspace.desired import ExperimentDesiredState, RadioDesiredState
from synthran.workspace.model import ExperimentRecord, WorkspaceError


class PromptLike(Protocol):
    def prompt(self, message: str, **kwargs) -> str: ...


def _ask(
    prompt: PromptLike,
    label: str,
    *,
    default: str | None = None,
    optional: bool = False,
) -> str | None:
    suffix = f" [{default}]" if default else ""
    value = prompt.prompt(f"{label}{suffix}: ").strip()
    if value:
        return value
    if default is not None:
        return default
    if optional:
        return None
    raise WorkspaceError(f"{label} is required")


def _yes(prompt: PromptLike, label: str, *, default: bool = True) -> bool:
    marker = "Y/n" if default else "y/N"
    value = prompt.prompt(f"{label} [{marker}]: ").strip().lower()
    if not value:
        return default
    if value in {"y", "yes"}:
        return True
    if value in {"n", "no"}:
        return False
    raise WorkspaceError(f"{label} requires yes or no")


def _radio(mode: str) -> RadioDesiredState:
    if mode == "virtual":
        return RadioDesiredState(mode="virtual", backend="rfsim")
    if mode == "physical":
        return RadioDesiredState(mode="physical", backend="r2lab")
    if mode == "automatic":
        return RadioDesiredState()
    raise WorkspaceError("radio mode must be automatic, virtual, or physical")


def ensure_active_experiment(
    *,
    application: ApplicationController,
    prompt: PromptLike,
    output: TextIO,
    environment: Mapping[str, str] | None = None,
) -> ExperimentRecord | None:
    """Offer local experiment creation when the initialized workspace is empty."""

    snapshot = application.snapshot()
    if snapshot.experiment_id is not None:
        return None
    if not _yes(prompt, "No active experiment. Create one now"):
        return None

    env = dict(os.environ if environment is None else environment)
    intent = _ask(prompt, "Experiment intent", default="iot-to-5g")
    assert intent is not None
    radio_mode = _ask(prompt, "Radio mode", default="virtual")
    assert radio_mode is not None
    provider_experiment = _ask(
        prompt,
        "SLICES provider experiment (blank to bind later)",
        default=env.get("SYNTHRAN_SLICES_EXPERIMENT"),
        optional=True,
    )
    label = _ask(prompt, "Experiment label (optional)", optional=True)

    desired = ExperimentDesiredState(
        intent=intent,
        radio=_radio(radio_mode),
    )
    record = application.create_experiment(
        desired=desired,
        label=label,
        slices_experiment=provider_experiment,
        activate=True,
    )
    print(
        f"Active experiment created: {record.experiment_id}",
        file=output,
        flush=True,
    )
    if record.slices_experiment is None:
        print(
            "Provider experiment is not bound yet; live control will remain fail-closed until it is bound.",
            file=output,
            flush=True,
        )
    return record
