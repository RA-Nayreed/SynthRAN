"""Cohesive physical R2Lab backend for SynthRAN.

The package is organized by subsystem rather than one file per live discovery:
provider control, radio/UE state, deployment, acceptance, and orchestration.
"""

from synthran.r2lab.controller import (
    R2LabDoctorReport,
    R2LabPlan,
    R2LabResourceError,
    R2LabResult,
    R2LabSelection,
    build_plan,
    execute_prepare,
    execute_release,
    gateway_command,
    run_doctor,
)

__all__ = [
    "R2LabDoctorReport",
    "R2LabPlan",
    "R2LabResourceError",
    "R2LabResult",
    "R2LabSelection",
    "build_plan",
    "execute_prepare",
    "execute_release",
    "gateway_command",
    "run_doctor",
]
