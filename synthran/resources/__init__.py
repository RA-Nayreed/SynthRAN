"""Provider-neutral resource requirements and deterministic placement."""

from synthran.resources.catalog import reviewed_resource_descriptors
from synthran.resources.decision import ResourceDecision, build_resource_decision
from synthran.resources.model import (
    ProviderResourceSet,
    ProviderResourceSnapshot,
    ResourceAssignment,
    ResourceDescriptor,
    ResourceInventory,
    ResourceRequirement,
    ResourceSelection,
    ResourceSelectionError,
    ResourceState,
)
from synthran.resources.requirements import (
    effective_radio_backend,
    requirements_from_desired,
)
from synthran.resources.selector import select_resources

__all__ = [
    "ProviderResourceSet",
    "ProviderResourceSnapshot",
    "ResourceAssignment",
    "ResourceDecision",
    "ResourceDescriptor",
    "ResourceInventory",
    "ResourceRequirement",
    "ResourceSelection",
    "ResourceSelectionError",
    "ResourceState",
    "build_resource_decision",
    "effective_radio_backend",
    "requirements_from_desired",
    "reviewed_resource_descriptors",
    "select_resources",
]
