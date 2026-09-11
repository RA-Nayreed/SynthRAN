"""Resolve public Docker Hub tags to immutable digest references."""
from __future__ import annotations

import argparse
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPOSITORY_RE = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$"
)
_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
_USER_AGENT = "SynthRAN-image-resolver/1"


def _normalize_docker_hub_repository(repository: str) -> tuple[str, str]:
    value = repository.strip()
    for prefix in ("docker.io/", "registry-1.docker.io/"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    if "/" in value:
        first = value.split("/", 1)[0]
        if "." in first or ":" in first or first == "localhost":
            raise ValueError(f"unsupported Docker Hub repository: {repository!r}")
    if not _REPOSITORY_RE.fullmatch(value):
        raise ValueError(f"unsupported Docker Hub repository: {repository!r}")
    canonical = value if "/" in value else f"library/{value}"
    return value, canonical


def resolve_docker_hub(reference_repository: str, tag: str, timeout: float = 20.0) -> str:
    display_repository, canonical_repository = _normalize_docker_hub_repository(reference_repository)
    tag = tag.strip()
    if not _TAG_RE.fullmatch(tag):
        raise ValueError(f"invalid Docker image tag: {tag!r}")

    query = urlencode(
        {
            "service": "registry.docker.io",
            "scope": f"repository:{canonical_repository}:pull",
        }
    )
    token_request = Request(
        f"https://auth.docker.io/token?{query}",
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
    )
    with urlopen(token_request, timeout=timeout) as response:  # nosec B310: fixed HTTPS host
        token_payload = json.load(response)
    token = token_payload.get("token") or token_payload.get("access_token")
    if not token:
        raise RuntimeError("Docker Hub did not return a pull token")

    manifest_request = Request(
        f"https://registry-1.docker.io/v2/{canonical_repository}/manifests/{tag}",
        method="HEAD",
        headers={
            "Accept": _ACCEPT,
            "Authorization": f"Bearer {token}",
            "User-Agent": _USER_AGENT,
        },
    )
    with urlopen(manifest_request, timeout=timeout) as response:  # nosec B310: fixed HTTPS host
        digest = (response.headers.get("Docker-Content-Digest") or "").strip().lower()
    if not _DIGEST_RE.fullmatch(digest):
        raise RuntimeError(f"Docker Hub returned an invalid manifest digest: {digest!r}")
    return f"{display_repository}@{digest}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)
    print(resolve_docker_hub(args.repository, args.tag, args.timeout))


if __name__ == "__main__":
    main()
