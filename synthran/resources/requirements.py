"""Pure translation from experiment intent to resource capability requirements."""

from __future__ import annotations

from synthran.resources.model import ResourceRequirement, ResourceSelectionError
from synthran.workspace.desired import ExperimentDesiredState


def effective_radio_backend(desired: ExperimentDesiredState) -> str:
    if desired.radio.backend != "automatic":
        return desired.radio.backend
    if desired.radio.mode == "virtual":
        return "rfsim"
    if desired.radio.mode == "physical":
        return "r2lab"
    if desired.intent == "virtual-5g":
        return "rfsim"
    if desired.intent == "physical-5g":
        return "r2lab"
    if desired.ran.implementation == "ueransim":
        return "rfsim"
    raise ResourceSelectionError(
        "automatic radio placement is ambiguous; choose virtual/RFSIM or physical/R2Lab"
    )


def requirements_from_desired(
    desired: ExperimentDesiredState,
) -> tuple[ResourceRequirement, ...]:
    """Build roles and capability constraints without reading provider state."""

    requirements: list[ResourceRequirement] = []
    manual = desired.placement.mode == "manual"

    if desired.core.enabled:
        requirements.append(
            ResourceRequirement(
                role="core",
                provider="slices",
                kind="compute",
                capabilities=frozenset({"compute", "role:core"}),
                pinned_ids=(
                    (desired.placement.core_node,)
                    if manual and desired.placement.core_node is not None
                    else ()
                ),
            )
        )

    if desired.ran.enabled:
        capabilities = {"compute", "role:ran"}
        if desired.multus.enabled and desired.multus.host_interface is not None:
            capabilities.add(f"interface:{desired.multus.host_interface}")
        requirements.append(
            ResourceRequirement(
                role="ran",
                provider="slices",
                kind="compute",
                capabilities=frozenset(capabilities),
                pinned_ids=(
                    (desired.placement.ran_node,)
                    if manual and desired.placement.ran_node is not None
                    else ()
                ),
            )
        )

    if manual and desired.placement.deployment_node is not None:
        requirements.append(
            ResourceRequirement(
                role="deployment",
                provider="slices",
                kind="compute",
                capabilities=frozenset({"compute", "role:deployment"}),
                pinned_ids=(desired.placement.deployment_node,),
            )
        )

    if manual:
        for ordinal, resource_id in enumerate(
            desired.placement.extra_resources, start=1
        ):
            requirements.append(
                ResourceRequirement(
                    role=f"extra{ordinal:03d}",
                    provider=None,
                    kind=None,
                    pinned_ids=(resource_id,),
                )
            )

    backend = effective_radio_backend(desired)
    ran_caps = (
        frozenset({f"ran:{desired.ran.implementation}"})
        if desired.ran.enabled and desired.ran.implementation != "automatic"
        else frozenset()
    )
    if backend == "rfsim":
        requirements.append(
            ResourceRequirement(
                role="radio",
                provider="virtual",
                kind="virtual",
                capabilities=frozenset({"radio", "backend:rfsim"}) | ran_caps,
            )
        )
    elif backend == "r2lab":
        capabilities = {"radio", "backend:r2lab"}
        capabilities.update(ran_caps)
        if desired.radio.hardware != "automatic":
            capabilities.add(f"hardware:{desired.radio.hardware}")
        requirements.append(
            ResourceRequirement(
                role="radio",
                provider="r2lab",
                kind="radio",
                capabilities=frozenset(capabilities),
            )
        )
        if desired.ue.enabled:
            requirements.append(
                ResourceRequirement(
                    role="ue",
                    provider="r2lab",
                    kind="ue",
                    capabilities=frozenset({"ue"}),
                    count=desired.ue.count,
                )
            )
    else:
        raise ResourceSelectionError("unsupported effective radio backend")

    return tuple(requirements)
