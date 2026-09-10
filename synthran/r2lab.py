"""Connection settings shared by inventory rendering and reservation commands."""

from __future__ import annotations

import os
from pathlib import Path


def access(deployment: dict) -> dict[str, str]:
    settings = deployment.get("r2lab_ssh", {})
    identity = os.environ.get("R2LAB_IDENTITY_FILE") or settings.get(
        "identity_file", ""
    )
    return {
        "host": settings.get("host", "faraday.inria.fr"),
        "username": os.environ.get("R2LAB_USERNAME")
        or settings.get("username")
        or deployment.get("r2lab_username", ""),
        "identity_file": str(Path(identity).expanduser()) if identity else "",
    }
