#!/usr/bin/env python3
"""Static contract checks for the simple interactive reservation UX."""

from pathlib import Path


class CheckError(RuntimeError):
    pass


def require(text: str, needle: str) -> None:
    if needle not in text:
        raise CheckError(f"deploy.sh is missing reservation wizard contract marker: {needle}")


def main() -> int:
    text = Path("deploy.sh").read_text(encoding="utf-8")
    markers = [
        "Ensure selected SOP nodes are reserved?",
        "How should SynthRAN prepare the selected SOP nodes?",
        "Reuse current node state",
        "Reset/reimage nodes before deployment",
        "SELECTED_RESERVATION_MODE=create",
        "SELECTED_RESERVATION_MODE=require-existing",
        "SELECTED_RESERVATION_MODE=disabled",
        "SELECTED_HOST_PREPARATION=fresh",
        "SELECTED_HOST_PREPARATION=preserve",
        "'mode': reservation_mode",
        "'host_preparation': host_preparation",
    ]
    for marker in markers:
        require(text, marker)

    for leaked_internal_label in (
        "SOP reservation policy (default:",
        "Create or reuse the exact selected-node reservation",
        "Require an existing exact selected-node reservation",
        "Disable SOP reservation management",
        "SOP host preparation policy (default:",
    ):
        if leaked_internal_label in text:
            raise CheckError(
                "internal reservation policy leaked back into the ordinary interactive UX: "
                + leaked_internal_label
            )

    if text.index("'mode': reservation_mode") > text.index("Path(output).write_text"):
        raise CheckError("reservation mode is not materialized before scenario write")
    if text.index("'host_preparation': host_preparation") > text.index("Path(output).write_text"):
        raise CheckError("host preparation is not materialized before scenario write")

    print("Reservation wizard contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
