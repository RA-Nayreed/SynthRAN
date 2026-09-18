#!/usr/bin/env python3
"""Static contract checks for the interactive reservation UX."""

from pathlib import Path


class CheckError(RuntimeError):
    pass


def require(text: str, needle: str) -> None:
    if needle not in text:
        raise CheckError(f"deploy.sh is missing reservation wizard contract marker: {needle}")


def main() -> int:
    text = Path("deploy.sh").read_text(encoding="utf-8")
    markers = [
        "How should SynthRAN use the SOP reservation?",
        "Use my existing exact reservation and verify remaining coverage",
        "Ensure an exact reservation exists (reuse/create as needed)",
        "Do not manage or verify a SOP reservation",
        "How should SynthRAN prepare the selected SOP nodes?",
        "Reuse current node state",
        "Reset/reimage nodes before deployment",
        "SELECTED_RESERVATION_MODE=require-existing",
        "SELECTED_RESERVATION_MODE=create",
        "SELECTED_RESERVATION_MODE=disabled",
        "SELECTED_HOST_PREPARATION=fresh",
        "SELECTED_HOST_PREPARATION=preserve",
        "SOP reservation authority disabled; host preparation is preserve-only.",
        "How should SynthRAN use the R2Lab booking?",
        "Use my existing booking and verify it covers this run",
        "Ensure a booking exists (reuse/extend/book as needed)",
        "Do not manage or verify an R2Lab booking",
        "SELECTED_R2LAB_MODE=require-existing",
        "SELECTED_R2LAB_MODE=book",
        "SELECTED_R2LAB_MODE=disabled",
        "'mode': reservation_mode",
        "'host_preparation': host_preparation",
        "'mode': r2lab_mode",
    ]
    for marker in markers:
        require(text, marker)

    for leaked_internal_label in (
        "SOP reservation policy (default:",
        "SOP host preparation policy (default:",
        "R2Lab reservation policy (default:",
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
    if text.index("'mode': r2lab_mode") > text.index("Path(output).write_text"):
        raise CheckError("R2Lab mode is not materialized before scenario write")

    if text.index("SELECTED_RESERVATION_MODE=require-existing") > text.index(
        "How should SynthRAN prepare the selected SOP nodes?"
    ):
        raise CheckError(
            "SOP reservation authority is not selected before host-preparation policy"
        )

    print("Reservation wizard contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
