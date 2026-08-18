# Composite resource transaction

SynthRAN's desired/resource model can describe experiments that require more than one provider. A modeled physical request can combine SLICES compute with an R2Lab radio/UE, while a virtual request combines SLICES compute with non-mutating `virtual:rfsim` placement.

The generic transaction layer coordinates provider boundaries without weakening provider-specific ownership checks. Its existence does **not** mean that every provider combination has a concrete production adapter or live acceptance.

## Preconditions

A resource transaction starts only after:

1. detailed desired state has been persisted;
2. fresh complete provider inventory has produced a `ResourceDecision`;
3. the exact decision has been bound into an immutable approved operation;
4. authorization has issued an `ExecutionPermit` whose targets exactly match the decision;
5. every real provider in the decision has a configured `ResourceProviderAdapter`.

Adapter presence is validated before the operation acquires mutation authority in the application-level execution path. Missing or mismatched adapters therefore cannot strand an authorized operation claim.

## Provider order

Current generic provider order is deterministic:

```text
SLICES -> R2Lab -> other real providers -> virtual
```

`virtual:rfsim` records placement scope but performs no acquisition call.

Ordering is not provider authority. Every concrete adapter must still perform its own current live safety checks immediately before each mutation.

## Acquisition receipt

A provider adapter returns an `AcquisitionReceipt` containing:

- provider;
- exact requested resource IDs;
- exact resource IDs created by this operation;
- status `ready` or `failed`.

`created_ids` is deliberately narrower than `requested_ids`. A requested resource that already existed safely before the operation was not created by the current operation and must not be added to generic rollback scope.

A receipt naming a resource outside its requested set is invalid.

## Rollback

When a provider explicitly reports failure, SynthRAN rolls back declared creations in reverse provider order.

Only exact `created_ids` are passed to `release()`. The transaction layer never expands rollback to the full requested set, infers ownership from a name, or issues global cleanup.

A successful `ReleaseReceipt` must prove that every requested rollback ID was released. If rollback is complete, transaction status is `rolled-back` and the operation engine can close the failure without retaining the mutation claim.

If release is incomplete or throws, transaction status is `recovery-required` and the operation claim remains held.

## Unknown partial failure

An adapter exception is different from an explicit failed receipt because the generic layer cannot know whether the failing provider changed state before raising.

In that case SynthRAN:

- marks that provider `acquire-unknown`;
- rolls back only exact creations already reported by earlier providers;
- does not guess cleanup scope for the failing provider;
- returns `recovery-required`;
- retains operation mutation authority for recovery.

Recovery must inspect current provider state and prove exact ownership before cleanup.

## Application integration

`ApplicationController.execute_resource_operation()` implements the high-level generic path:

```text
approved resource-bound operation
    + fresh current inventory
    + configured provider adapters
    -> validate adapters
    -> authorize operation and acquire exclusive mutation claim
    -> execute_resource_transaction()
       -> ready             => operation completed, claim released
       -> rolled-back       => failed cleanly, claim released
       -> recovery-required => recovery required, claim retained
```

Unexpected exceptions after authorization are recorded as interruption rather than treated as proof that providers were unchanged.

## Adapter contract

A transaction adapter is intentionally small:

```text
provider: str
acquire(exact_ids, permit) -> AcquisitionReceipt
release(exact_created_ids, permit) -> ReleaseReceipt
```

The generic layer does not itself parse POS ownership, create SLICES reservations/allocations, book R2Lab leases, power radios, image nodes, or deploy network software.

Concrete provider adapters must wrap reviewed provider-specific safety logic and recheck authority immediately before mutation.

For SLICES, a concrete generic adapter must treat the selected compute set as one acquisition unit and verify that all required nodes end in the same appropriate owned allocation. It must not reproduce per-node free/allocate behavior that can split the requested pair across unrelated allocations.

For R2Lab, a concrete generic adapter must check the active lease immediately before physical mutation and release only exact changes created by the operation.

## Current product boundary

The generic transaction model/engine is implemented and offline tested. Concrete generic SLICES and R2Lab transaction adapters are not yet connected to the production interactive terminal.

The repository does contain older/provider-specific scripted executors for current live workflows. Those are separate execution paths and are not automatically substituted behind `ApplicationController.execute_resource_operation()`.

Consequences for the stock terminal today:

- resource-bound `/reserve` and `/up` first require a production `ResourceInventory` source, which is not yet wired into the shell;
- even after a valid resource operation plan exists, a concrete provider adapter is required before generic execution can occur;
- physical R2Lab selection/model support is not physical 5G path acceptance.

Do not describe the generic transaction engine as proof that interactive SLICES acquisition or physical R2Lab operation is already live operational.
