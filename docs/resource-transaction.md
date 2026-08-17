# Composite resource transaction

SynthRAN can require resources from more than one provider. A physical experiment can combine SLICES compute with an R2Lab radio and UE, while a virtual experiment combines SLICES compute with the non-mutating `virtual:rfsim` placement.

The composite transaction layer coordinates those provider boundaries without weakening provider-specific ownership checks.

## Preconditions

A resource transaction starts only after:

1. detailed desired state has been persisted;
2. fresh complete provider inventory has produced a `ResourceDecision`;
3. the exact decision has been bound into an immutable approved operation;
4. authorization has issued an `ExecutionPermit` whose targets exactly match the decision;
5. every real provider in the decision has a configured transaction adapter.

Adapter presence is validated before the operation acquires mutation authority in the application-level execution path. Missing or mismatched adapters therefore cannot strand an authorized operation claim.

## Provider order

Current provider order is deterministic:

```text
SLICES -> R2Lab -> other real providers -> virtual
```

The ordering makes compute acquisition happen before physical R2Lab activation. `virtual:rfsim` records placement scope but performs no acquisition call.

The ordering is not provider authority. Every adapter must still perform its own current live safety checks immediately before each actual mutation.

## Acquisition receipt

A provider adapter returns an `AcquisitionReceipt` with:

- provider;
- exact requested resource IDs;
- exact resource IDs created by this operation;
- status `ready` or `failed`.

`created_ids` is deliberately narrower than `requested_ids`. A requested resource that was already safely held before the operation is not created by the current operation and therefore must not be included in rollback scope.

A receipt that names a resource outside its requested set is invalid.

## Rollback

When a provider explicitly reports failure, SynthRAN rolls back declared creations in reverse provider order.

Only `created_ids` are passed to `release()`. The transaction layer never expands rollback to the full requested set, never infers ownership from a name, and never issues global cleanup.

A successful `ReleaseReceipt` must prove that every requested rollback ID was released. If rollback is complete, the transaction result is `rolled-back` and the operation engine may release its exclusive mutation claim while recording the operation as failed.

If any release is incomplete or throws an exception, transaction status is `recovery-required` and the operation claim remains held.

## Unknown partial failure

An adapter exception is treated differently from an explicit failed receipt. The transaction does not know whether the failing provider changed some resources before the exception.

In that case SynthRAN:

- marks that provider `acquire-unknown`;
- rolls back only exact creations previously reported by earlier providers;
- does not guess a cleanup set for the failing provider;
- returns `recovery-required`;
- retains the operation mutation claim.

A later recovery operation must inspect live provider state and prove exact ownership before cleanup.

## Application integration

`ApplicationController.execute_resource_operation()` provides the high-level path:

```text
approved operation
    + fresh current inventory
    + configured provider adapters
    -> validate adapters
    -> authorize operation and acquire exclusive mutation claim
    -> execute composite transaction
       -> ready            => operation completed, claim released
       -> rolled-back      => operation failed cleanly, claim released
       -> recovery-required => operation recovery-required, claim retained
```

Any unexpected exception after authorization records interruption and retains the claim rather than assuming the providers are unchanged.

## Adapter contract

A transaction adapter is intentionally small:

```text
provider: str
acquire(exact_ids, permit) -> AcquisitionReceipt
release(exact_created_ids, permit) -> ReleaseReceipt
```

Concrete SLICES and R2Lab adapters must wrap the already reviewed provider-specific safety logic. The generic transaction layer does not parse POS ownership, book R2Lab leases, power radios, image nodes, or deploy network software by itself.

For SLICES, a future adapter must treat the selected compute set as one acquisition unit and verify that all required nodes end in the same owned allocation. It must not copy per-node free/allocate behavior that can split nodes across allocations.

For R2Lab, an adapter must continue checking the active lease immediately before each physical-resource mutation and may release only the exact radio/UE changes created by the current operation.
