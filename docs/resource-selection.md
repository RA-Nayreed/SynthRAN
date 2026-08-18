# Capability-based resource selection

SynthRAN separates stable resource capability metadata from current provider state. A resource is never considered available merely because its name exists in source code.

The selector is pure and non-executing. It consumes requested experiment state plus fresh, complete provider inventory and returns one deterministic placement. Reservation, allocation, lease, power, imaging, and deployment remain separate provider actions.

## Inputs

Selection has three input classes:

1. `ExperimentDesiredState` describes what the experiment needs.
2. `ResourceDescriptor` records reviewed stable metadata such as provider, resource kind, capabilities, and role preference.
3. `ProviderResourceSnapshot` records current availability and ownership returned by a provider query.

A descriptor does not carry current availability. A provider snapshot does not redefine stable hardware capabilities.

## Current reviewed catalog

The catalog currently describes resources already modeled by reviewed SynthRAN integration code:

- SLICES compute: `sopnode-f1`, `sopnode-f2`, `sopnode-f3`, `sopnode-w3`;
- R2Lab radios: `n300`, `n320`;
- the reviewed QHAT/QFIT UE identifiers supported by the R2Lab resource-control model;
- one synthetic `virtual:rfsim` resource.

The SLICES role preferences preserve the recommended `sopnode-f2` core and `sopnode-f3` RAN pair when all else is equal. This is only a ranking preference. If a preferred node is unavailable, unsafe, or incompatible, another reviewed compatible resource can be selected.

R2Lab descriptors represent combinations understood by the resource-selection/provider-control code. They do **not** constitute live physical 5G path acceptance. Physical radio acceptance remains deferred until an actual R2Lab radio/UE path is exercised and evidenced end to end.

Additional descriptors can be supplied without changing the selector after their stable capabilities and provider-control implications are reviewed.

## Provider inventory contract

A provider snapshot has:

- provider name;
- observation time;
- explicit freshness boundary;
- a `complete` flag;
- current per-resource availability and ownership.

Automatic placement requires a fresh, complete snapshot for every real provider it needs. Partial or stale inventory fails closed because absence from a partial result cannot be interpreted as unavailability.

Current availability states are:

```text
available
allocated
unavailable
unknown
```

Current ownership states are:

```text
synthran
operator
other
unknown
unowned
```

Only `available` or `allocated` resources with ownership `synthran`, `operator`, or `unowned` are selection candidates. Foreign or unknown ownership is never selected automatically.

Selection does not turn `operator` ownership into SynthRAN mutation authority. Provider executors must still prove exact live authority immediately before mutation.

### Read-only SLICES compute inventory

The interactive workbench can now request a live placement preview for the reviewed SLICES compute catalog. The adapter first requires a fresh cached SLICES access record matching the selected profile and project. It then performs only these POS reads:

```text
pos calendar list --json
pos allocations list --json
```

Reservation and allocation data are combined before a node is classified. An active reservation owned by another operator makes the node unavailable even when no allocation exists. Foreign allocations are also unsafe. Conflicting ownership, overlapping active reservations, duplicate allocation records, malformed provider output, failed commands, and incomplete reads fail closed.

A free node is represented as `available/unowned`. A node actively reserved by the current operator but not yet allocated is represented as `available/operator`. Current allocations retain their observed ownership. The snapshot covers all reviewed SLICES compute descriptors and is marked complete only after both POS reads validate successfully.

The default freshness window is short, and it is shortened further to end before any known reservation start or end that could change availability. A placement preview therefore cannot be reused indefinitely as provider truth.

The Resources view invokes this provider read only when the operator presses Enter. Normal workbench startup remains local-only. The result is passed through the existing `ResourceDecision` path; no parallel placement algorithm exists in the UI.

This interface currently supplies live SLICES compute inventory only. Virtual RFSIM needs no real-provider snapshot. A physical-radio request still fails closed because a current complete R2Lab radio/UE inventory is not yet connected to this preview path.

## Requirements derived from experiment state

Requested state becomes role requirements rather than fixed node names.

Examples:

```text
core       -> SLICES compute with role:core
ran        -> SLICES compute with role:ran
radio      -> virtual RFSIM or R2Lab radio
ue         -> R2Lab UE resources for physical-radio experiments
deployment -> explicitly pinned SLICES compute when requested
extraNNN   -> explicitly pinned extra resource
```

If Multus requests a host interface, the RAN compute requirement includes that interface capability.

For physical radio, an explicit `n300` or `n320` request becomes a hardware capability requirement. An explicit RAN implementation also becomes a compatibility requirement on the radio.

Virtual RFSIM does not require an R2Lab provider snapshot or lease.

An experiment whose automatic radio configuration is genuinely ambiguous is rejected rather than guessed. The caller must resolve it to virtual/RFSIM or physical/R2Lab.

## Manual placement

Manual placement is a hard constraint, not a hint. A pinned resource must:

- exist in the reviewed descriptor set supplied to selection;
- belong to the expected provider and resource kind;
- satisfy required capabilities;
- appear in a fresh complete current provider snapshot;
- have safe current ownership and availability.

A manual pin therefore cannot bypass provider-state safety.

## Deterministic ranking

When more than one placement is valid, SynthRAN ranks whole resource sets in this order:

1. fewer unowned resources, so compatible already-held resources are reused first;
2. fewer merely operator-owned resources, preferring exact SynthRAN-held resources when possible;
3. lower reviewed role-preference score;
4. fewer distinct resources;
5. lexical resource IDs as a deterministic final tie-break.

Explicit manual pins are applied before ranking, so they always win when safe and compatible.

Core and RAN assignments are non-overlapping in the current selector. This matches the current SLICES preparation contract, which prepares separate core and RAN compute nodes.

## Provider resource sets

The output contains role assignments and the same assignments grouped by provider. For example:

```text
slices  -> sopnode-f2, sopnode-f3
virtual -> virtual:rfsim
```

or, for a modeled physical request:

```text
slices -> sopnode-f2, sopnode-f3
r2lab  -> n300, qhat01
```

The grouped SLICES set is important: a concrete acquisition adapter must reason about the compute selection as one set. It must not reproduce per-node free/allocate behavior that can split an experiment across unrelated allocations.

For R2Lab, selection only chooses a compatible radio/UE set. It does not book a lease. R2Lab mutation still requires a current active lease and the provider-specific live safety checks.

## Safety boundary

`ResourceSelection` is placement output, not authority. It may be persisted as planning evidence, but it cannot authorize a reservation, allocation, lease, power action, or deployment by itself.

The execution chain remains:

```text
desired state
    -> fresh complete provider inventory
    -> select_resources()
    -> ResourceDecision for exact operation binding when required
    -> current observed-state / application policy
    -> immutable OperationPlan
    -> approval when required
    -> ExecutionPermit
    -> provider live authority check
    -> exact provider mutation
```

The interactive terminal now has a read-only SLICES placement preview, but concrete mutation adapters for the complete dynamic provider path are still not connected to it. The preview therefore must not be documented as proof that terminal reservation, allocation, deployment, or physical R2Lab execution is live operational.
