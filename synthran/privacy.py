"""Sensitive-context scanning and deterministic text redaction."""

from __future__ import annotations

from dataclasses import dataclass
import getpass
import ipaddress
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Iterable, Iterator, Sequence, TextIO


MAX_TEXT_BYTES = 2 * 1024 * 1024
ZERO_SHA = "0" * 40


class PrivacyError(RuntimeError):
    """Raised when a privacy operation cannot be performed safely."""


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    commit: str | None = None

    def location(self) -> str:
        prefix = f"{self.commit[:12]}:" if self.commit else ""
        return f"{prefix}{self.path}:{self.line}"


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]


STATIC_RULES = (
    Rule(
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    Rule(
        "provider-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"),
    ),
    Rule(
        "kubeconfig-embedded-secret",
        re.compile(r"(?i)\b(?:client-key-data|client-certificate-data)\s*:"),
    ),
    Rule(
        "subscriber-secret",
        re.compile(r"(?i)\b(?:opc|full_key|auth(?:entication)?_key)\s*[:=]\s*['\"]?[0-9a-f]{32}\b"),
    ),
    Rule(
        "imsi",
        re.compile(r"(?<![0-9])(?:[0-9]{14,16})(?![0-9])"),
    ),
    Rule(
        "windows-absolute-path",
        re.compile(r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/](?![<>])[^\r\n`'\"]+)"),
    ),
    Rule(
        "posix-user-home",
        re.compile(r"(?<![A-Za-z0-9])/(?:home|Users)/[A-Za-z0-9._-]+(?:/[^\s`'\"]*)?"),
    ),
    Rule(
        "unc-path",
        re.compile(r"\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9$._-]+"),
    ),
)

ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?:[A-Za-z0-9]+[_-])*"
    r"(password|passwd|secret|token|api[_-]?key|client[_-]?secret)\b"
    r"\s*[:=]\s*([^\s,;#]+)"
)

WINDOWS_HOME_RE = re.compile(r"(?i)\b[A-Z]:[\\/]Users[\\/][^\\/\s`'\"]+")
POSIX_HOME_RE = re.compile(r"(?<![A-Za-z0-9])/(?:home|Users)/[A-Za-z0-9._-]+")
UNC_PREFIX_RE = re.compile(r"\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9$._-]+")
IPV4_RE = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
ULA_IPV6_RE = re.compile(r"(?i)(?<![0-9a-f:])(?:fc|fd)[0-9a-f]{2}(?::[0-9a-f]{0,4}){1,7}(?![0-9a-f:])")


def _is_placeholder(value: str) -> bool:
    normalized = value.strip("'\" ").lower()
    if not normalized:
        return True
    placeholder_markers = (
        "${",
        "${{",
        "<",
        "example",
        "placeholder",
        "redacted",
        "changeme",
        "dummy",
        "github.token",
    )
    return normalized.startswith(placeholder_markers)


def local_identifiers() -> tuple[str, ...]:
    candidates = {
        getpass.getuser(),
        Path.home().name,
        os.environ.get("USERNAME", ""),
        os.environ.get("USER", ""),
    }
    ignored = {"", "root", "runner", "system", "administrator", "user", "unknown"}
    return tuple(
        sorted(
            {
                value
                for value in candidates
                if len(value) >= 4 and value.lower() not in ignored
            },
            key=str.lower,
        )
    )


def scan_text(
    text: str,
    *,
    path: str,
    commit: str | None = None,
    identifiers: Sequence[str] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    names = tuple(local_identifiers() if identifiers is None else identifiers)
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule in STATIC_RULES:
            if rule.pattern.search(line):
                findings.append(Finding(rule.name, path, line_number, commit))

        assignment = ASSIGNMENT_RE.search(line)
        if assignment and not _is_placeholder(assignment.group(2)):
            findings.append(Finding("credential-assignment", path, line_number, commit))

        for name in names:
            if re.search(rf"(?i)(?<![A-Za-z0-9_.-]){re.escape(name)}(?![A-Za-z0-9_.-])", line):
                findings.append(Finding("local-username", path, line_number, commit))
                break

    unique: dict[tuple[str, str, int, str | None], Finding] = {}
    for finding in findings:
        unique[(finding.rule, finding.path, finding.line, finding.commit)] = finding
    return list(unique.values())


def _decode_text(data: bytes) -> str | None:
    if len(data) > MAX_TEXT_BYTES or b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _git(repo: Path, *args: str, input_text: str | None = None, check: bool = True) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            input=input_text.encode("utf-8") if input_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
        )
    except FileNotFoundError as exc:
        raise PrivacyError("git is required but was not found") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise PrivacyError(f"git command failed: {detail}") from exc
    return completed.stdout


def repository_root(start: Path | None = None) -> Path:
    base = (start or Path.cwd()).resolve()
    raw = _git(base, "rev-parse", "--show-toplevel")
    return Path(raw.decode("utf-8").strip()).resolve()


def _split_nul(data: bytes) -> list[str]:
    return [item.decode("utf-8") for item in data.split(b"\x00") if item]


def scan_worktree(repo: Path) -> list[Finding]:
    names = _split_nul(_git(repo, "ls-files", "-co", "--exclude-standard", "-z"))
    findings: list[Finding] = []
    for relative in names:
        path = repo / relative
        if not path.is_file():
            continue
        try:
            text = _decode_text(path.read_bytes())
        except OSError as exc:
            raise PrivacyError(f"cannot read tracked candidate {relative}: {exc}") from exc
        if text is not None:
            findings.extend(scan_text(text, path=relative))
    return findings


def _commit_paths(repo: Path, commit: str) -> Iterator[str]:
    raw = _git(
        repo,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "--diff-filter=ACMR",
        "-r",
        "-z",
        commit,
    )
    yield from _split_nul(raw)


def scan_commits(repo: Path, commits: Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for commit in commits:
        for relative in _commit_paths(repo, commit):
            key = (commit, relative)
            if key in seen:
                continue
            seen.add(key)
            completed = subprocess.run(
                ["git", "show", f"{commit}:{relative}"],
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if completed.returncode != 0:
                continue
            text = _decode_text(completed.stdout)
            if text is not None:
                findings.extend(scan_text(text, path=relative, commit=commit))
    return findings


def scan_history(repo: Path) -> list[Finding]:
    commits = _git(repo, "rev-list", "--all").decode("ascii").splitlines()
    return scan_commits(repo, commits)


def outgoing_commits(repo: Path, remote: str, updates: Iterable[str]) -> list[str]:
    commits: list[str] = []
    seen: set[str] = set()
    for update in updates:
        fields = update.strip().split()
        if not fields:
            continue
        if len(fields) != 4:
            raise PrivacyError("unexpected pre-push input")
        _local_ref, local_sha, _remote_ref, remote_sha = fields
        if local_sha == ZERO_SHA:
            continue
        if remote_sha == ZERO_SHA:
            args = ("rev-list", local_sha, "--not", f"--remotes={remote}")
        else:
            args = ("rev-list", f"{remote_sha}..{local_sha}")
        for commit in _git(repo, *args).decode("ascii").splitlines():
            if commit not in seen:
                seen.add(commit)
                commits.append(commit)
    return commits


def report_findings(findings: Sequence[Finding], output: TextIO) -> int:
    if not findings:
        print("privacy scan passed", file=output)
        return 0
    print(f"privacy scan blocked {len(findings)} finding(s):", file=output)
    for finding in sorted(findings, key=lambda item: (item.location(), item.rule)):
        print(f"- {finding.rule}: {finding.location()}", file=output)
    print("Detected values are intentionally omitted from this output.", file=output)
    return 1


class TextRedactor:
    """Replace sensitive local context with stable, non-reversible placeholders."""

    def __init__(self, identifiers: Sequence[str] | None = None) -> None:
        self.identifiers = tuple(local_identifiers() if identifiers is None else identifiers)
        self._private_ipv4: dict[str, str] = {}
        self._private_ipv6: dict[str, str] = {}

    @staticmethod
    def _token(mapping: dict[str, str], value: str, prefix: str) -> str:
        if value not in mapping:
            mapping[value] = f"<{prefix}_{len(mapping) + 1}>"
        return mapping[value]

    def _replace_ipv4(self, match: re.Match[str]) -> str:
        value = match.group(0)
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return value
        private = (
            address in ipaddress.ip_network("10.0.0.0/8")
            or address in ipaddress.ip_network("172.16.0.0/12")
            or address in ipaddress.ip_network("192.168.0.0/16")
        )
        if not private:
            return value
        return self._token(self._private_ipv4, value, "PRIVATE_IPV4")

    def _replace_ipv6(self, match: re.Match[str]) -> str:
        value = match.group(0)
        return self._token(self._private_ipv6, value.lower(), "PRIVATE_IPV6")

    def redact(self, text: str) -> str:
        redacted = WINDOWS_HOME_RE.sub("<USER_HOME>", text)
        redacted = POSIX_HOME_RE.sub("<USER_HOME>", redacted)
        redacted = UNC_PREFIX_RE.sub("<NETWORK_SHARE>", redacted)
        for name in self.identifiers:
            redacted = re.sub(
                rf"(?i)(?<![A-Za-z0-9_.-]){re.escape(name)}(?![A-Za-z0-9_.-])",
                "<USER>",
                redacted,
            )
        redacted = IPV4_RE.sub(self._replace_ipv4, redacted)
        redacted = ULA_IPV6_RE.sub(self._replace_ipv6, redacted)
        return redacted


def redact_file(source: Path, destination: Path, *, dry_run: bool, output: TextIO) -> None:
    source_resolved = source.resolve()
    destination_resolved = destination.resolve(strict=False)
    if source_resolved == destination_resolved:
        raise PrivacyError("redaction output must differ from the source")
    data = source.read_bytes()
    text = _decode_text(data)
    if text is None:
        raise PrivacyError("redaction accepts UTF-8 text files up to 2 MiB only")
    redacted = TextRedactor().redact(text)
    if dry_run:
        print("[dry-run] sanitized text would be written to the requested output", file=output)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=destination.parent,
        delete=False,
    ) as temporary:
        temporary.write(redacted)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, destination)
    print("sanitized text written", file=output)
