from __future__ import annotations

from dataclasses import dataclass
import unittest

from synthran.operations.model import ExecutionPermit
from synthran.resources import (
    AcquisitionReceipt,
    ProviderResourceSet,
    ReleaseReceipt,
    ResourceAssignment,
    ResourceDecision,
    ResourceSelection,
    ResourceState,
    ResourceTransactionError,
    execute_resource_transaction,
)


@dataclass
class FakeAdapter:
    provider: str
    acquire_status: str = "ready"
    acquire_created: tuple[str, ...] | None = None
    acquire_raises: bool = False
    release_status: str = "ready"
    release_raises: bool = False

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def acquire(
        self,
        resource_ids: tuple[str, ...],
        permit: ExecutionPermit,
    ) -> AcquisitionReceipt:
        self.calls.append(("acquire", resource_ids))
        if self.acquire_raises:
            raise RuntimeError("private provider failure")
        created = self.acquire_created
        if created is None:
            created = resource_ids if self.acquire_status == "ready" else ()
        return AcquisitionReceipt(
            provider=self.provider,
            requested_ids=resource_ids,
            created_ids=created,
            status=self.acquire_status,
        )

    def release(
        self,
        resource_ids: tuple[str, ...],
        permit: ExecutionPermit,
    ) -> ReleaseReceipt:
        self.calls.append(("release", resource_ids))
        if self.release_raises:
            raise RuntimeError("private rollback failure")
        released = resource_ids if self.release_status == "ready" else ()
        return ReleaseReceipt(
            provider=self.provider,
            requested_ids=resource_ids,
            released_ids=released,
            status=self.release_status,
        )


def physical_decision() -> ResourceDecision:
    assignments = (
        ResourceAssignment("core", 1, "sopnode-f2", "slices", "compute", "unowned"),
        ResourceAssignment("radio", 1, "n300", "r2lab", "radio", "unowned"),
        ResourceAssignment("ran", 1, "sopnode-f3", "slices", "compute", "unowned"),
        ResourceAssignment("ue", 1, "qhat01", "r2lab", "ue", "unowned"),
    )
    selection = ResourceSelection(
        assignments=assignments,
        provider_sets=(
            ProviderResourceSet("r2lab", ("n300", "qhat01")),
            ProviderResourceSet("slices", ("sopnode-f2", "sopnode-f3")),
        ),
    )
    return ResourceDecision(
        selection=selection,
        states=tuple(
            ResourceState(item.resource_id, "available", "unowned")
            for item in assignments
        ),
    )


def virtual_decision() -> ResourceDecision:
    assignments = (
        ResourceAssignment("core", 1, "sopnode-f2", "slices", "compute", "unowned"),
        ResourceAssignment("radio", 1, "virtual:rfsim", "virtual", "virtual", "unowned"),
        ResourceAssignment("ran", 1, "sopnode-f3", "slices", "compute", "unowned"),
    )
    selection = ResourceSelection(
        assignments=assignments,
        provider_sets=(
            ProviderResourceSet("slices", ("sopnode-f2", "sopnode-f3")),
            ProviderResourceSet("virtual", ("virtual:rfsim",)),
        ),
    )
    return ResourceDecision(
        selection=selection,
        states=tuple(
            ResourceState(item.resource_id, "available", "unowned")
            for item in assignments
        ),
    )


def permit(decision: ResourceDecision) -> ExecutionPermit:
    return ExecutionPermit(
        operation_id="op-000001",
        experiment_id="sran-20260817-001",
        kind="allocate",
        risk="R2",
        mutates=True,
        plan_sha256="a" * 64,
        issued_at_utc="2026-08-17T19:00:00Z",
        targets=decision.targets,
    )


class ResourceTransactionTests(unittest.TestCase):
    def test_all_adapters_are_validated_before_any_provider_call(self) -> None:
        decision = physical_decision()
        slices = FakeAdapter("slices")
        with self.assertRaises(ResourceTransactionError):
            execute_resource_transaction(
                permit=permit(decision),
                decision=decision,
                adapters={"slices": slices},
            )
        self.assertEqual(slices.calls, [])

    def test_success_acquires_slices_before_r2lab_and_never_rolls_back(self) -> None:
        decision = physical_decision()
        order: list[str] = []

        class OrderedAdapter(FakeAdapter):
            def acquire(self, resource_ids, execution_permit):
                order.append(self.provider)
                return super().acquire(resource_ids, execution_permit)

        slices = OrderedAdapter("slices")
        r2lab = OrderedAdapter("r2lab")
        result = execute_resource_transaction(
            permit=permit(decision),
            decision=decision,
            adapters={"slices": slices, "r2lab": r2lab},
        )
        self.assertEqual(result.status, "ready")
        self.assertEqual(order, ["slices", "r2lab"])
        self.assertFalse(any(call[0] == "release" for call in slices.calls + r2lab.calls))

    def test_declared_provider_failure_rolls_back_exact_created_ids_in_reverse(self) -> None:
        decision = physical_decision()
        slices = FakeAdapter(
            "slices",
            acquire_created=("sopnode-f2",),
        )
        r2lab = FakeAdapter(
            "r2lab",
            acquire_status="failed",
            acquire_created=("n300",),
        )
        result = execute_resource_transaction(
            permit=permit(decision),
            decision=decision,
            adapters={"slices": slices, "r2lab": r2lab},
        )
        self.assertEqual(result.status, "rolled-back")
        self.assertEqual(r2lab.calls[-1], ("release", ("n300",)))
        self.assertEqual(slices.calls[-1], ("release", ("sopnode-f2",)))
        self.assertNotIn(("release", ("sopnode-f2", "sopnode-f3")), slices.calls)

    def test_provider_exception_is_unknown_partial_state_and_requires_recovery(self) -> None:
        decision = physical_decision()
        slices = FakeAdapter("slices")
        r2lab = FakeAdapter("r2lab", acquire_raises=True)
        result = execute_resource_transaction(
            permit=permit(decision),
            decision=decision,
            adapters={"slices": slices, "r2lab": r2lab},
        )
        self.assertEqual(result.status, "recovery-required")
        self.assertEqual(result.failed_provider, "r2lab")
        self.assertEqual(
            slices.calls[-1],
            ("release", ("sopnode-f2", "sopnode-f3")),
        )
        self.assertFalse(any(call[0] == "release" for call in r2lab.calls))

    def test_rollback_failure_requires_recovery(self) -> None:
        decision = physical_decision()
        slices = FakeAdapter("slices", release_raises=True)
        r2lab = FakeAdapter("r2lab", acquire_status="failed")
        result = execute_resource_transaction(
            permit=permit(decision),
            decision=decision,
            adapters={"slices": slices, "r2lab": r2lab},
        )
        self.assertEqual(result.status, "recovery-required")
        self.assertTrue(result.recovery_required)

    def test_already_held_resource_is_never_in_rollback_scope(self) -> None:
        decision = physical_decision()
        slices = FakeAdapter(
            "slices",
            acquire_created=("sopnode-f2",),
        )
        r2lab = FakeAdapter("r2lab", acquire_status="failed")
        result = execute_resource_transaction(
            permit=permit(decision),
            decision=decision,
            adapters={"slices": slices, "r2lab": r2lab},
        )
        self.assertTrue(result.clean_failure)
        self.assertIn(("release", ("sopnode-f2",)), slices.calls)
        self.assertFalse(
            any("sopnode-f3" in resource_ids for action, resource_ids in slices.calls if action == "release")
        )

    def test_target_mismatch_fails_before_any_provider_call(self) -> None:
        decision = physical_decision()
        wrong = ExecutionPermit(
            operation_id="op-000001",
            experiment_id="sran-20260817-001",
            kind="allocate",
            risk="R2",
            mutates=True,
            plan_sha256="a" * 64,
            issued_at_utc="2026-08-17T19:00:00Z",
            targets=("sopnode-f2",),
        )
        slices = FakeAdapter("slices")
        r2lab = FakeAdapter("r2lab")
        with self.assertRaises(ResourceTransactionError):
            execute_resource_transaction(
                permit=wrong,
                decision=decision,
                adapters={"slices": slices, "r2lab": r2lab},
            )
        self.assertEqual(slices.calls, [])
        self.assertEqual(r2lab.calls, [])

    def test_virtual_resource_needs_no_adapter_or_mutation(self) -> None:
        decision = virtual_decision()
        slices = FakeAdapter("slices")
        result = execute_resource_transaction(
            permit=permit(decision),
            decision=decision,
            adapters={"slices": slices},
        )
        self.assertEqual(result.status, "ready")
        virtual = next(record for record in result.records if record.provider == "virtual")
        self.assertEqual(virtual.status, "no-mutation")


if __name__ == "__main__":
    unittest.main()
