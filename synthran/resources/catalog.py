"""Reviewed stable capability metadata for currently supported testbed resources."""

from __future__ import annotations

from synthran.resources.model import ResourceDescriptor


SLICES_COMPUTE = (
    ResourceDescriptor(
        resource_id="sopnode-f1",
        provider="slices",
        kind="compute",
        capabilities=frozenset(
            {
                "compute",
                "role:core",
                "role:ran",
                "role:deployment",
                "kubernetes",
                "interface:ens2f1",
                "storage:sda1",
            }
        ),
        role_priority={"core": 20, "ran": 20, "deployment": 20},
    ),
    ResourceDescriptor(
        resource_id="sopnode-f2",
        provider="slices",
        kind="compute",
        capabilities=frozenset(
            {
                "compute",
                "role:core",
                "role:ran",
                "role:deployment",
                "kubernetes",
                "interface:ens2f1",
                "storage:sda1",
            }
        ),
        role_priority={"core": 0, "ran": 10, "deployment": 10},
    ),
    ResourceDescriptor(
        resource_id="sopnode-f3",
        provider="slices",
        kind="compute",
        capabilities=frozenset(
            {
                "compute",
                "role:core",
                "role:ran",
                "role:deployment",
                "kubernetes",
                "fhi72",
                "interface:ens15f1",
                "storage:sdb2",
            }
        ),
        role_priority={"core": 10, "ran": 0, "deployment": 10},
    ),
    ResourceDescriptor(
        resource_id="sopnode-w3",
        provider="slices",
        kind="compute",
        capabilities=frozenset(
            {
                "compute",
                "role:core",
                "role:ran",
                "role:deployment",
                "kubernetes",
                "interface:enp59s0f1np1",
                "storage:sda1",
            }
        ),
        role_priority={"core": 30, "ran": 30, "deployment": 30},
    ),
)


R2LAB_RADIOS = (
    ResourceDescriptor(
        resource_id="n300",
        provider="r2lab",
        kind="radio",
        capabilities=frozenset(
            {
                "radio",
                "backend:r2lab",
                "hardware:n300",
                "ran:oai",
                "ran:srsran",
            }
        ),
        role_priority={"radio": 0},
    ),
    ResourceDescriptor(
        resource_id="n320",
        provider="r2lab",
        kind="radio",
        capabilities=frozenset(
            {
                "radio",
                "backend:r2lab",
                "hardware:n320",
                "ran:oai",
                "ran:srsran",
            }
        ),
        role_priority={"radio": 10},
    ),
)


_QHAT_MBIM = ("qhat01", "qhat02", "qhat03", "qhat10", "qhat11")
_QHAT_QMI = ("qhat20", "qhat21", "qhat22")
_QFIT_MBIM = ("qfit07", "qfit09", "qfit18", "qfit29", "qfit32", "qfit34")

R2LAB_UES = tuple(
    ResourceDescriptor(
        resource_id=name,
        provider="r2lab",
        kind="ue",
        capabilities=frozenset({"ue", "device:qhat", "mode:mbim"}),
        role_priority={"ue": 10},
    )
    for name in _QHAT_MBIM
) + tuple(
    ResourceDescriptor(
        resource_id=name,
        provider="r2lab",
        kind="ue",
        capabilities=frozenset({"ue", "device:qhat", "mode:qmi"}),
        role_priority={"ue": 20},
    )
    for name in _QHAT_QMI
) + tuple(
    ResourceDescriptor(
        resource_id=name,
        provider="r2lab",
        kind="ue",
        capabilities=frozenset({"ue", "device:qfit", "mode:mbim"}),
        role_priority={"ue": 30},
    )
    for name in _QFIT_MBIM
)


VIRTUAL_RESOURCES = (
    ResourceDescriptor(
        resource_id="virtual:rfsim",
        provider="virtual",
        kind="virtual",
        capabilities=frozenset(
            {
                "radio",
                "radio:virtual",
                "backend:rfsim",
                "ran:oai",
                "ran:srsran",
                "ran:ueransim",
            }
        ),
        role_priority={"radio": 0},
    ),
)


def reviewed_resource_descriptors() -> tuple[ResourceDescriptor, ...]:
    """Return stable metadata only; callers must obtain live provider state separately."""

    return SLICES_COMPUTE + R2LAB_RADIOS + R2LAB_UES + VIRTUAL_RESOURCES
