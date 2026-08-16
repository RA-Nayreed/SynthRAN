"""Unified SynthRAN command-line entrypoint."""

from __future__ import annotations

from typing import Sequence

from synthran.cli import _parser, main


if __name__ == "__main__":
    raise SystemExit(main())
