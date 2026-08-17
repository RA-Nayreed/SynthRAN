"""Transactional multi-provider resource acquisition with exact rollback scope."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Protocol, runtime_checkable

from synthran.operations.model import ExecutionPermit
from synthran.resources.decision import ResourceDecision
from synthran.resources.model import ProviderResourceSet, ResourceSelectionError


PROVIDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ACQUISITION_STATUSES = frozenset({"ready", "failed"})
RELEASE_STATUSES = frozenset({"ready", "failed"})
TRANSACTION_STATUSES = frozenset({"ready", "rolled-back", "recovery-required"})
PROVIDER_ORDER = {"slices": 10, "r2lab": 20}


class ResourceTransactionError(ResourceSelectionError):
    """Raised when a resource transaction cannot be started safely."""


def _provider(value: str) -> str:
    if PROVIDER_RE.fullmatch(value) is None:
        raise ResourceTransactionError("provider name contains unsupported characters")
    return value


def _ids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ResourceTransactionError(f"{label} resource IDs must be unique")
    return values


@dataclass(frozen=True)
class AcquisitionReceipt:
    """Provider-declared result; created IDs are the only rollback authority."""

    provider: str
    requested_ids: tuple[str, ...]
    created_ids: tuple[str, ...]
    status: str

    def __post_init__(self) -> None:
        _provider(self.provider)
        _ids(self.requested_ids, "acquisition requested")
        _ids(self.created_ids, "acquisition created")
        if self.status not in ACQUISITION_STATUSES:
            raise ResourceTransactionError("acquisition receipt status is unsupported")
        if not set(self.created_ids).issubset(self.requested_ids):
            raise ResourceTransactionError(
                "acquisition receipt claims resources outside the requested set"
            )


@dataclass(frozen=True)
class ReleaseReceipt:
    """Provider-declared exact rollback result."""

    provider: str
    requested_ids: tuple[str, ...]
    released_ids: tuple[str, ...]
    status: str

    def __post_init__(self) -> None:
        _provider(self.provider)
        _ids(self.requested_ids, "release requested")
        _ids(self.released_ids, "release completed")
        if self.status not in RELEASE_STATUSES:
            raise ResourceTransactionError("release receipt status is unsupported")
        if not set(self.released_ids).issubset(self.requested_ids):
            raise ResourceTransactionError(
                "release receipt claims resources outside the rollback set"
            )
        if self.status == "ready" and set(self.released_ids) != set(self.requested_ids):
            raise ResourceTransactionError(
                "successful release receipt must cover every requested rollback resource"
            )


@runtime_checkable
class ResourceProviderAdapter(Protocol):
    provider: str

    def acquire(
        self,
        resource_ids: tuple[str, ...],
        permit: ExecutionPermit,
    ) -> AcquisitionReceipt: ...

    def release(
        self,
        resource_ids: tuple[str, ...],
        permit: ExecutionPermit,
    ) -> ReleaseReceipt: ...


@dataclass(frozen=True)
class ProviderTransactionRecord:
    provider: str
    requested_ids: tuple[str, ...]
    created_ids: tuple[str, ...] = ()
    released_ids: tuple[str, ...] = ()
    status: str = "ready"

    def __post_init__(self) -> None:
        _provider(self.provider)
        _ids(self.requested_ids, "provider transaction requested")
        _ids(self.created_ids, "provider transaction created")
        _ids(self.released_ids, "provider transaction released")
        if self.status not in {
            "ready",
            "acquire-failed",
            "acquire-unknown",
            "rolled-back",
            "rollback-failed",
            "no-mutation",
        }:
            raise ResourceTransactionError("provider transaction status is unsupported")
        if not set(self.created_ids).issubset(self.requested_ids):
            raise ResourceTransactionError(
                "provider transaction created resources outside requested scope"
            )
        if not set(self.released_ids).issubset(self.created_ids):
            raise ResourceTransactionError(
                "provider transaction released resources outside created scope"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "requested_ids": list(self.requested_ids),
            "created_ids": list(self.created_ids),
            "released_ids": list(self.released_ids),
            "status": self.status,
        }


@dataclass(frozen=True)
class ResourceTransactionResult:
    status: str
    records: tuple[ProviderTransactionRecord, ...]
    failed_provider: str | None = None

    def __post_init__(self) -> None:
        if self.status not in TRANSACTION_STATUSES:
            raise ResourceTransactionError("resource transaction status is unsupported")
        if self.failed_provider is not None:
            _provider(self.failed_provider)
        if self.status == "ready" and self.failed_provider is not None:
            raise ResourceTransactionError(
                "ready resource transaction cannot contain a failed provider"
            )
        providers = [item.provider for item in self.records]
        if len(providers) != len(set(providers)):
            raise ResourceTransactionError(
                "resource transaction result must contain one final record per provider"
            )

    @property
    def clean_failure(self) -> bool:
        return self.status == "rolled-back"

    @property
    def recovery_required(self) -> bool:
        return self.status == "recovery-required"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "failed_provider": self.failed_provider,
            "records": [item.to_dict() for item in self.records],
        }


def _ordered_provider_sets(
    decision: ResourceDecision,
) -> tuple[ProviderResourceSet, ...]:
    return tuple(
        sorted(
            decision.selection.provider_sets,
            key=lambda item: (
                PROVIDER_ORDER.get(item.provider, 100),
                item.provider,
            ),
        )
    )


def validate_resource_adapters(
    decision: ResourceDecision,
    adapters: Mapping[str, ResourceProviderAdapter],
) -> tuple[ProviderResourceSet, ...]:
    """Validate every real provider adapter before any operation acquires mutation authority."""

    groups = _ordered_provider_sets(decision)
    grouped_ids = tuple(
        sorted(
            resource_id
            for group in groups
            for resource_id in group.resource_ids
        )
    )
    if grouped_ids != decision.targets:
        raise ResourceTransactionError(
            "resource decision provider sets do not cover the exact target scope"
        )

    for group in groups:
        if group.provider == "virtual":
            continue
        adapter = adapters.get(group.provider)
        if adapter is None:
            raise ResourceTransactionError(
                f"no resource adapter is configured for provider {group.provider}"
            )
        if not isinstance(adapter, ResourceProviderAdapter):
            raise ResourceTransactionError(
                f"resource adapter for {group.provider} does not implement the transaction contract"
            )
        if adapter.provider != group.provider:
            raise ResourceTransactionError(
                f"resource adapter provider mismatch for {group.provider}"
            )
    return groups


def _validate_transaction_scope(
    permit: ExecutionPermit,
    decision: ResourceDecision,
    adapters: Mapping[str, ResourceProviderAdapter],
) -> tuple[ProviderResourceSet, ...]:
    if not permit.mutates:
        raise ResourceTransactionError(
            "read-only execution permit cannot start a resource transaction"
        )
    if not permit.targets:
        raise ResourceTransactionError(
            "resource transaction requires an execution permit with exact targets"
        )
    if tuple(sorted(permit.targets)) != decision.targets:
        raise ResourceTransactionError(
            "execution permit targets do not match the resource decision"
        )
    return validate_resource_adapters(decision, adapters)


def _validate_acquisition(
    receipt: AcquisitionReceipt,
    *,
    provider: str,
    requested_ids: tuple[str, ...],
) -> None:
    if receipt.provider != provider:
        raise ResourceTransactionError("acquisition receipt provider mismatch")
    if tuple(receipt.requested_ids) != tuple(requested_ids):
        raise ResourceTransactionError("acquisition receipt requested scope mismatch")


def _rollback(
    completed: list[tuple[ResourceProviderAdapter, AcquisitionReceipt]],
    *,
    permit: ExecutionPermit,
) -> tuple[list[ProviderTransactionRecord], bool]:
    records: list[ProviderTransactionRecord] = []
    clean = True
    for adapter, acquisition in reversed(completed):
        if not acquisition.created_ids:
            records.append(
                ProviderTransactionRecord(
                    provider=acquisition.provider,
                    requested_ids=acquisition.requested_ids,
                    created_ids=(),
                    released_ids=(),
                    status=(
                        "acquire-failed"
                        if acquisition.status == "failed"
                        else "rolled-back"
                    ),
                )
            )
            continue
        try:
            release = adapter.release(acquisition.created_ids, permit)
            if (
                release.provider != acquisition.provider
                or release.requested_ids != acquisition.created_ids
            ):
                clean = False
                records.append(
                    ProviderTransactionRecord(
                        provider=acquisition.provider,
                        requested_ids=acquisition.requested_ids,
                        created_ids=acquisition.created_ids,
                        status="rollback-failed",
                    )
                )
                continue
            fully_released = (
                release.status == "ready"
                and set(release.released_ids) == set(acquisition.created_ids)
            )
            clean = clean and fully_released
            records.append(
                ProviderTransactionRecord(
                    provider=acquisition.provider,
                    requested_ids=acquisition.requested_ids,
                    created_ids=acquisition.created_ids,
                    released_ids=release.released_ids,
                    status="rolled-back" if fully_released else "rollback-failed",
                )
            )
        except Exception:
            clean = False
            records.append(
                ProviderTransactionRecord(
                    provider=acquisition.provider,
                    requested_ids=acquisition.requested_ids,
                    created_ids=acquisition.created_ids,
                    status="rollback-failed",
                )
            )
    return records, clean


def _unaffected_records(
    ready_records: list[ProviderTransactionRecord],
    completed: list[tuple[ResourceProviderAdapter, AcquisitionReceipt]],
) -> list[ProviderTransactionRecord]:
    rolled_back = {receipt.provider for _, receipt in completed}
    return [item for item in ready_records if item.provider not in rolled_back]


def execute_resource_transaction(
    *,
    permit: ExecutionPermit,
    decision: ResourceDecision,
    adapters: Mapping[str, ResourceProviderAdapter],
) -> ResourceTransactionResult:
    """Acquire provider sets in order and roll back only exact declared creations."""

    groups = _validate_transaction_scope(permit, decision, adapters)
    completed: list[tuple[ResourceProviderAdapter, AcquisitionReceipt]] = []
    ready_records: list[ProviderTransactionRecord] = []

    for group in groups:
        if group.provider == "virtual":
            ready_records.append(
                ProviderTransactionRecord(
                    provider="virtual",
                    requested_ids=group.resource_ids,
                    status="no-mutation",
                )
            )
            continue

        adapter = adapters[group.provider]
        try:
            receipt = adapter.acquire(group.resource_ids, permit)
            _validate_acquisition(
                receipt,
                provider=group.provider,
                requested_ids=group.resource_ids,
            )
        except Exception:
            rollback_records, _ = _rollback(completed, permit=permit)
            return ResourceTransactionResult(
                status="recovery-required",
                records=tuple(
                    _unaffected_records(ready_records, completed)
                    + [
                        ProviderTransactionRecord(
                            provider=group.provider,
                            requested_ids=group.resource_ids,
                            status="acquire-unknown",
                        )
                    ]
                    + rollback_records
                ),
                failed_provider=group.provider,
            )

        completed.append((adapter, receipt))
        if receipt.status == "failed":
            rollback_records, clean = _rollback(completed, permit=permit)
            return ResourceTransactionResult(
                status="rolled-back" if clean else "recovery-required",
                records=tuple(
                    _unaffected_records(ready_records, completed)
                    + rollback_records
                ),
                failed_provider=group.provider,
            )

        ready_records.append(
            ProviderTransactionRecord(
                provider=receipt.provider,
                requested_ids=receipt.requested_ids,
                created_ids=receipt.created_ids,
                status="ready",
            )
        )

    return ResourceTransactionResult(
        status="ready",
        records=tuple(ready_records),
    )
