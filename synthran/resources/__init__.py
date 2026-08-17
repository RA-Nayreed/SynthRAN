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
from synthran.resources.transaction import (
    AcquisitionReceipt,
    ProviderTransactionRecord,
    ReleaseReceipt,
    ResourceProviderAdapter,
    ResourceTransactionError,
    ResourceTransactionResult,
    execute_resource_transaction,
)

__all__ = [
    "AcquisitionReceipt",
    "ProviderResourceSet",
    "ProviderResourceSnapshot",
    "ProviderTransactionRecord",
    "ReleaseReceipt",
    "ResourceAssignment",
    "ResourceDecision",
    "ResourceDescriptor",
    "ResourceInventory",
    "ResourceProviderAdapter",
    "ResourceRequirement",
    "ResourceSelection",
    "ResourceSelectionError",
    "ResourceState",
    "ResourceTransactionError",
    "ResourceTransactionResult",
    "build_resource_decision",
    "effective_radio_backend",
    "execute_resource_transaction",
    "requirements_from_desired",
    "reviewed_resource_descriptors",
    "select_resources",
]
