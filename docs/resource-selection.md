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

The catalog currently describes the resources already supported elsewhere in SynthRAN:

- SLICES compute: `sopnode-f1`, `sopnode-f2`, `sopnode-f3`, `sopnode-w3`;
- R2Lab radios: `n300`, `n320`;
- the QHAT and QFIT UEs already accepted by the R2Lab provider;
- one synthetic `virtual:rfsim` resource.

The SLICES role preferences preserve the currently recommended `sopnode-f2` core and `sopnode-f3` RAN pair when all else is equal. This is only a ranking preference. If the preferred node is unavailable, unsafe, or incompatible, another current compatible resource can be selected.

The R2Lab radio descriptors expose the RAN combinations already supported by the reviewed deployment tooling. The catalog intentionally does not claim support for additional RUs until the corresponding SynthRAN provider adapter can control them safely.

Additional descriptors can be supplied without changing the selector. This is how new testbed resources can be introduced after their capabilities are reviewed.

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

The selector does not turn `operator` ownership into SynthRAN mutation authority. Provider executors must still prove exact live authority immediately before any mutation.

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

Explicit manual pins are applied before ranking, so they always win when they are safe and compatible.

Core and RAN assignments are non-overlapping in the current selector. This matches the existing SLICES preparation contract, which prepares a separate core and RAN node.

## Provider resource sets

The output contains role assignments and the same assignments grouped by provider. For example:

```text
slices  -> sopnode-f2, sopnode-f3
virtual -> virtual:rfsim
```

or:

```text
slices -> sopnode-f2, sopnode-f3
r2lab  -> n300, qhat01
```

The grouped SLICES set is important: a later acquisition adapter must reason about the compute selection as one set. It must not reproduce per-node free/allocate behavior that can split an experiment across unrelated allocations.

For R2Lab, selection only chooses a compatible radio/UE set. It does not book a lease. The R2Lab provider continues to require a current active lease immediately before every physical-resource mutation.

## Safety boundary

`ResourceSelection` is placement output, not authority. It may be persisted later as planning evidence, but it cannot authorize a reservation, allocation, lease, power action, or deployment by itself.

The execution chain remains:

```text
desired state
    -> fresh complete provider inventory
    -> capability selection
    -> observed-state reconciliation
    -> immutable operation plan
    -> approval when required
    -> execution permit
    -> provider live authority check
    -> exact provider mutation
```

This lets placement become dynamic without weakening the ownership and freshness rules already enforced by SynthRAN.
