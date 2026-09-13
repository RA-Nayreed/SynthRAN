"""Compatibility import for legacy experiment scripts.

New experiment code belongs in :mod:`synthran.experiments`. This module is kept
only while the retained Experiment 2 pilot scripts are migrated; do not add new
logic here.
"""

from synthran.experiments import load_scenario, remap_gateways, scientific_settings

__all__ = ["load_scenario", "remap_gateways", "scientific_settings"]
