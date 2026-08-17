# Resource-bound operation approval

Dynamic placement must not create a gap between what the operator approves and what a provider executor later changes. SynthRAN therefore binds placement into the immutable operation plan for resource-changing actions.

## Resource decision

A `ResourceDecision` contains:

- the exact deterministic `ResourceSelection`;
- the current availability and ownership state of every selected resource.

The decision intentionally excludes provider observation timestamps. Freshness is checked independently whenever the decision is built. This means a harmless provider refresh with the same selected resources and the same availability/ownership can still validate an existing approval, while a resource-state or placement change invalidates it.

The decision may include virtual resources such as `virtual:rfsim`. These identifiers describe the complete placement scope; a provider executor still acts only on resources belonging to its provider.

## Operation binding

For placement mutations such as `reserve`, `allocate`, `prepare`, and `up`, the application controller requires fresh complete provider inventory before it creates an operation.

The resulting operation plan stores:

```text
targets        = exact selected resource IDs
input_sha256   = SHA256 of the resource decision
```

The full current inventory is not copied into the operation plan. Availability and ownership facts are represented by the decision digest, while the exact selected IDs remain visible for review and executor scoping.

Older operation plans that do not contain targets or extra input digests retain their original canonical digest shape. Empty optional fields are omitted from `unsigned_dict()` rather than being injected retroactively.

## Approval and authorization

Approval is still bound to the operation plan digest. Because the resource-decision digest participates in the plan digest, approval covers the exact placement decision that existed when the operation was created.

Immediately before authorization, the application controller requires a new fresh complete inventory whenever the plan contains a resource-decision binding. It reruns placement and compares:

- exact target IDs;
- selected availability and ownership;
- the resulting resource-decision digest;
- desired state;
- reconciled observed state;
- reconciliation policy.

If any of those inputs changed, authorization fails. The operator creates a new operation from the new state rather than reusing the old approval.

Provider snapshot timestamps are not themselves operation-bound. A refreshed snapshot with unchanged selected state therefore does not cause false drift.

## Execution permit

The ephemeral `ExecutionPermit` carries the exact plan targets. This lets a provider executor refuse any mutation outside the approved resource scope.

The permit does not replace live provider checks. Immediately before each actual mutation, the executor must still prove current provider authority and ownership. A resource becoming foreign, unknown, unavailable, or otherwise unsafe after authorization remains non-mutable.

## Application boundary

The shared application controller owns the resource-binding workflow:

```text
active desired state
    + current provider inventory
    -> ResourceDecision
    + current observed state
    -> immutable OperationPlan
    -> operator approval
    + refreshed provider inventory
    -> recomputed ResourceDecision
    -> ExecutionPermit with exact targets
    -> provider live safety checks
    -> exact mutation
```

Read-only R0/R1 actions do not require a resource decision unless a future adapter explicitly needs one. This keeps status and verification paths usable without manufacturing placement authority.
