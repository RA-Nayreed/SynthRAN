"""Versioned read-only control interface for external SynthRAN clients."""

from synthran.control.server import ControlService, serve

__all__ = ["ControlService", "serve"]
