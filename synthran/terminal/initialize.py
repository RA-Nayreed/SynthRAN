"""First-launch terminal initialization using the verified workspace service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Protocol, TextIO

from synthran.workspace.initialization import (
    InitializationRequest,
    InitializationResult,
    initialize_controller_workspace,
)
from synthran.workspace.model import WorkspaceError
from synthran.workspace.store import (
    DEFAULT_PROFILE_NAME,
    profile_path,
    workspace_directory,
    workspace_file,
)


PRIVATE_KEY_BEGIN = b"-----BEGIN "
PRIVATE_KEY_SUFFIX = b" KEY-----"
PRIVATE_KEY_MARKER = b"PRIVATE"
INITIALIZATION_PROVIDER_TIMEOUT_SECONDS = 60


class PromptLike(Protocol):
    def prompt(self, message: str, **kwargs) -> str: ...


def initialization_root(start: Path | None = None) -> Path:
    """Prefer the nearest existing SynthRAN/git project root for first-use state."""

    current = (start or Path.cwd()).expanduser().resolve()
    home = Path.home().resolve()
    for candidate in (current, *current.parents):
        if workspace_file(candidate).is_file():
            return candidate
        if candidate != home and workspace_directory(candidate).exists():
            return candidate
        if (candidate / ".git").exists():
            return candidate
    return current


def _ask(
    prompt: PromptLike,
    label: str,
    *,
    default: str | None = None,
) -> str:
    suffix = f" [{default}]" if default else ""
    value = prompt.prompt(f"{label}{suffix}: ").strip()
    if value:
        return value
    if default is not None:
        return default
    raise WorkspaceError(f"{label} is required")


def _yes(prompt: PromptLike, label: str, *, default: bool = False) -> bool:
    marker = "Y/n" if default else "y/N"
    value = prompt.prompt(f"{label} [{marker}]: ").strip().lower()
    if not value:
        return default
    if value in {"y", "yes"}:
        return True
    if value in {"n", "no"}:
        return False
    raise WorkspaceError(f"{label} requires yes or no")


def _environment_home(environment: Mapping[str, str]) -> Path:
    configured = environment.get("HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home().resolve()


def _looks_like_private_identity(prefix: bytes) -> bool:
    first_line = prefix.splitlines()[0] if prefix else b""
    return (
        first_line.startswith(PRIVATE_KEY_BEGIN)
        and first_line.endswith(PRIVATE_KEY_SUFFIX)
        and PRIVATE_KEY_MARKER in first_line
    )


def discover_ssh_identities(
    environment: Mapping[str, str] | None = None,
) -> tuple[Path, ...]:
    """Return private SSH identities found directly below the user's ~/.ssh directory."""

    env = dict(os.environ if environment is None else environment)
    ssh_directory = _environment_home(env) / ".ssh"
    if not ssh_directory.is_dir():
        return ()

    identities: list[Path] = []
    for candidate in ssh_directory.iterdir():
        if not candidate.is_file() or candidate.name.endswith(".pub"):
            continue
        try:
            with candidate.open("rb") as stream:
                prefix = stream.read(256)
        except OSError:
            continue
        if _looks_like_private_identity(prefix):
            identities.append(candidate.resolve())

    return tuple(
        sorted(
            identities,
            key=lambda path: ("r2lab" not in path.name.lower(), path.name.lower()),
        )
    )


def _display_identity(path: Path, home: Path) -> str:
    try:
        relative = path.relative_to(home)
    except ValueError:
        return str(path)
    return f"~/{relative.as_posix()}"


def _select_ssh_identity(
    *,
    prompt: PromptLike,
    output: TextIO,
    environment: Mapping[str, str],
) -> Path:
    identities = discover_ssh_identities(environment)
    if not identities:
        return Path(_ask(prompt, "R2Lab SSH identity")).expanduser()

    home = _environment_home(environment)
    print("Available SSH identities:", file=output, flush=True)
    for index, identity in enumerate(identities, start=1):
        print(
            f"  {index}) {_display_identity(identity, home)}",
            file=output,
            flush=True,
        )
    print("  m) Enter another path", file=output, flush=True)

    selection = _ask(prompt, "R2Lab SSH identity", default="1")
    if selection.isdigit():
        index = int(selection)
        if 1 <= index <= len(identities):
            return identities[index - 1]
        raise WorkspaceError("R2Lab SSH identity selection is out of range")
    if selection.lower() == "m":
        return Path(_ask(prompt, "R2Lab SSH identity path")).expanduser()
    return Path(selection).expanduser()


def initialize_from_terminal(
    *,
    root: Path,
    prompt: PromptLike,
    output: TextIO,
    environment: Mapping[str, str] | None = None,
) -> InitializationResult:
    """Collect stable identity choices, verify access read-only, then persist locally."""

    env = dict(os.environ if environment is None else environment)
    target = root.expanduser().resolve()
    if workspace_file(target).is_file():
        raise WorkspaceError("SynthRAN workspace is already initialized")

    print("SynthRAN workspace initialization", file=output, flush=True)
    if workspace_directory(target).exists():
        print(
            "Existing .synthran run artifacts detected; compatible legacy artifacts will be preserved.",
            file=output,
            flush=True,
        )

    profile_name = _ask(prompt, "Controller profile", default=DEFAULT_PROFILE_NAME)
    project = _ask(
        prompt,
        "SLICES project",
        default=env.get("SYNTHRAN_SLICES_PROJECT"),
    )

    existing_profile = profile_path(profile_name, environment=env).is_file()
    slices_username: str | None = None
    r2lab_slice: str | None = None
    r2lab_identity: Path | None = None
    if existing_profile:
        print(f"Reusing controller profile: {profile_name}", file=output, flush=True)
    else:
        slices_username = _ask(prompt, "SLICES username")
        if _yes(prompt, "Configure R2Lab access now"):
            r2lab_slice = _ask(prompt, "R2Lab slice")
            r2lab_identity = _select_ssh_identity(
                prompt=prompt,
                output=output,
                environment=env,
            )

    request = InitializationRequest(
        root=target,
        project=project,
        profile_name=profile_name,
        slices_username=slices_username,
        r2lab_slice=r2lab_slice,
        r2lab_identity=r2lab_identity,
        reuse_profile=existing_profile,
    )

    print("Verifying provider access read-only...", file=output, flush=True)
    result = initialize_controller_workspace(
        request,
        environment=env,
        timeout_seconds=INITIALIZATION_PROVIDER_TIMEOUT_SECONDS,
    )
    print(
        f"Workspace initialized: project={result.workspace.project}, profile={result.workspace.profile}",
        file=output,
        flush=True,
    )
    return result
