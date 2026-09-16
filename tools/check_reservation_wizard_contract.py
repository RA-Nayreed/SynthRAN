#!/usr/bin/env python3
"""Static contract checks for interactive reservation policy selection."""

from pathlib import Path


class CheckError(RuntimeError):
    pass


def require(text: str, needle: str) -> None:
    if needle not in text:
        raise CheckError(f"deploy.sh is missing reservation wizard contract marker: {needle}")


def main() -> int:
    text = Path("deploy.sh").read_text(encoding="utf-8")
    markers = [
        "SOP reservation policy (default: $DEFAULT_RESERVATION_MODE)",
        "Create or reuse the exact selected-node reservation",
        "Require an existing exact selected-node reservation",
        "Disable SOP reservation management",
        "SOP host preparation policy (default: $DEFAULT_HOST_PREPARATION)",
        "Fresh - prove allocation ownership, image, boot parameters, reset, readiness",
        "Preserve - keep existing host state; no image/reset/bootparameter mutation",
        "SELECTED_RESERVATION_MODE=create",
        "SELECTED_RESERVATION_MODE=require-existing",
        "SELECTED_RESERVATION_MODE=disabled",
        "SELECTED_HOST_PREPARATION=fresh",
        "SELECTED_HOST_PREPARATION=preserve",
        "'mode': reservation_mode",
        "'host_preparation': host_preparation",
        "POS reservation: $SELECTED_RESERVATION_MODE",
        "POS host state:  $SELECTED_HOST_PREPARATION",
    ]
    for marker in markers:
        require(text, marker)

    old_prompt = "Ensure selected SOP nodes are reserved?"
    if old_prompt in text:
        raise CheckError(
            "legacy boolean-only reservation prompt returned; interactive policy must be explicit"
        )

    if text.index("'mode': reservation_mode") > text.index("Path(output).write_text"):
        raise CheckError("reservation mode is not materialized before scenario write")
    if text.index("'host_preparation': host_preparation") > text.index("Path(output).write_text"):
        raise CheckError("host preparation is not materialized before scenario write")

    print("Reservation wizard contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
