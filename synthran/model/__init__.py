"""6G model primitives and deterministic workload engine.

NOTE: Capacitor/Controller/BaseStation/CoverageMap/BackscatterModule/BSBehavior
below are legacy copies of the Amber engine (see THIRD_PARTY_NOTICES.md). The
full, canonical Amber source now lives at the repository root under `amber/`
(see third_party/amber/SOURCE.json for provenance). These copies are kept
as-is for now to avoid breaking existing imports, and are scheduled for
consolidation onto `amber/` -- see docs/amber-integration-plan.md for the
staged plan. `EnergyWorkloadModel` (engine.py) and `EnergyTrace` (energy.py)
are SynthRAN-original and are not derived from Amber.
"""
from .engine import EnergyWorkloadModel
from .capacitor import Capacitor, CapacitorParams
from .controller import Controller, ControllerParams
from .radiodevices import BaseStation, Sector, Node
from .propagation import CoverageMap
from .backscatter import BackscatterModule
from .bsengine import BSBehavior

__all__ = ["EnergyWorkloadModel", "Capacitor", "CapacitorParams", "Controller", "ControllerParams", "BaseStation", "Sector", "Node", "CoverageMap", "BackscatterModule", "BSBehavior"]
