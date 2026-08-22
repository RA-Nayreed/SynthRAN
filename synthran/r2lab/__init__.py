"""Cohesive physical R2Lab backend for SynthRAN.

The package is organized by subsystem rather than one file per live discovery:
provider control, radio/UE state, deployment, acceptance, runtime verification,
and orchestration.
"""

from synthran.r2lab.controller import (
    R2LabDoctorReport,
    R2LabPlan,
    R2LabResourceError,
    R2LabResult,
    R2LabSelection,
    build_plan,
    execute_physical_gnb_start,
    execute_prepare,
    execute_release,
    gateway_command,
    run_doctor,
)
from synthran.r2lab.runtime import (
    GnbN2Evidence,
    N2State,
    PhysicalRuntimeVerificationResult,
    R2LabRuntimeVerificationError,
    execute_physical_runtime_verification,
    execute_qfit_management_probe,
    execute_qfit_runtime_probe,
    parse_n2_log_state,
    verify_gnb_n2,
)

__all__ = [
    "GnbN2Evidence",
    "N2State",
    "PhysicalRuntimeVerificationResult",
    "R2LabDoctorReport",
    "R2LabPlan",
    "R2LabResourceError",
    "R2LabResult",
    "R2LabRuntimeVerificationError",
    "R2LabSelection",
    "build_plan",
    "execute_physical_gnb_start",
    "execute_physical_runtime_verification",
    "execute_prepare",
    "execute_qfit_management_probe",
    "execute_qfit_runtime_probe",
    "execute_release",
    "gateway_command",
    "parse_n2_log_state",
    "run_doctor",
    "verify_gnb_n2",
]
