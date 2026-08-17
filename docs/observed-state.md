# Observed state and reconciliation contract

SynthRAN separates requested state from current infrastructure facts.

The requested network is stored in `desired.json`. Current provider/runtime facts are collected independently and reduced into an `ObservedState` snapshot. A persisted `observed.json` is useful for terminal rendering and evidence inspection, but it remains a cache and never grants mutation authority by itself.

## Truth ranking

When several sources describe the same state dimension, SynthRAN uses this order:

```text
live provider
live direct observation
persisted evidence
local manifest
cache
```

The implementation represents these sources as:

```text
provider
observation
evidence
manifest
cache
```

Live provider/direct observations require an explicit freshness boundary. They cannot remain live forever just because no new query was made.

Truth selection first considers current observations. Among current observations, source authority wins before timestamp. If no current observation exists, the same source ranking chooses the best historical fallback. Historical fallback may be shown to the operator but does not become current mutation authority.

## Observed dimensions

The current model contains these dimensions:

```text
controller
project_access
provider_experiment
reservation
allocation
preparation
kubernetes
core
ran
ue
pdu
upf
radio
r2lab_lease
iot
path
experiment
dataset
```

Each observation includes:

- state;
- source;
- observation time;
- freshness boundary when applicable;
- ownership;
- optional resource ID;
- bounded detail text;
- bounded scalar facts.

Runtime facts such as a dynamically assigned PDU address belong here rather than in `desired.json`.

## Observation states

State values are deliberately generic:

```text
unknown
absent
pending
ready
degraded
failed
blocked
```

Provider adapters translate their native status into this common vocabulary.

## Ownership

Observed resources use:

```text
synthran
operator
other
unknown
unowned
```

Only a fresh live observation of a `synthran`-owned resource can authorize automatic mutation of an existing resource.

An operator-owned reservation or allocation can be recognized as usable when the provider proves it belongs to the current operator, but SynthRAN does not treat it as its own cleanup authority. Foreign or unknown ownership blocks mutation.

An absent resource can be `unowned`; that permits a later approved create operation after provider authority has been verified.

## Persisted snapshot

A reconciled snapshot is stored as:

```text
.synthran/experiments/<experiment-id>/observed.json
```

This document records the best observation selected for each dimension at collection time. It can be replaced as newer observations arrive.

Persisting the snapshot does not change source authority. A cached copy of a provider result is still historical when its freshness boundary passes.

## Lifecycle

The current experiment lifecycle is derived from desired state plus current observations:

```text
CONFIGURED
RESERVED
ALLOCATED
PREPARED
NETWORK_READY
PATH_PROVEN
EXPERIMENT_RUNNING
RECOVERY_REQUIRED
BLOCKED
```

`PATH_PROVEN` requires a current path observation. A historical successful measurement remains valid research evidence, but it does not claim that the current network is still usable.

`EXPERIMENT_RUNNING` requires a current experiment observation with `running=true`.

A current critical failure yields `RECOVERY_REQUIRED`. A current explicit block yields `BLOCKED`.

## Fail-closed reconciliation

`plan_reconciliation()` is pure. It does not execute shell commands or provider mutations. It emits only the next safe boundary.

Typical sequence:

```text
inspect authority
inspect reservation
reserve
inspect allocation
allocate
check physical-radio lease when required
inspect preparation
prepare
inspect network
up
verify path
```

The planner stops when an earlier dependency is unknown. It never skips an inspection and mutates a later resource based on assumptions.

Examples:

- unknown reservation -> `inspect-reservation`, no mutation;
- absent reservation -> approved `reserve` step;
- unknown allocation ownership -> `BLOCKED`;
- incomplete SynthRAN-owned allocation -> approved `recover-allocation` step;
- incomplete operator-owned allocation -> `BLOCKED`;
- physical radio without an active R2Lab lease -> `obtain-r2lab-lease` requirement;
- prepared resources with absent network components -> approved `up` step;
- ready network without current path proof -> read-only `verify-path` step.

## Risk classes

Reconciliation steps use the operator policy risk classes:

```text
R0  read-only inspection or external requirement
R1  non-destructive verification
R2  approved resource/network mutation
R3  explicitly destructive mutation
```

The current reconciler never emits an R3 step. Teardown/cleanup policy remains separate and must verify exact ownership before destructive action.

## Provider adapters

Provider-specific code is responsible for producing observations, not for changing the truth hierarchy.

For example:

- SLICES reports project experiment, reservation, and allocation facts;
- POS reports preparation/allocation runtime facts;
- Kubernetes reports core/RAN/UE/service state;
- network verification reports PDU, UPF, and path facts;
- R2Lab reports lease, radio, and UE hardware facts.

The terminal shell consumes the reconciled common model. It should not duplicate provider-specific status logic.
