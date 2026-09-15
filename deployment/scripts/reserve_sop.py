#!/usr/bin/env python3
"""Compatibility entrypoint for SynthRAN's authoritative reservation layer."""

from synthran.reservation import main


if __name__ == "__main__":
    raise SystemExit(main())
