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

The implementation source tokens are:

```text
provider
observation
evidence
manifest
cache
```

Live provider/direct observations require an explicit freshness boundary. They cannot remain current indefinitely because no newer query was made.

Truth selection first considers current observations. Among current observations, source authority wins before timestamp. If no current observation exists, the same ranking chooses the best historical fallback. Historical fallback may be shown to the operator but does not become current mutation authority.

## Observed dimensions

The current model contains:

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

State values are:

```text
unknown
absent
pending
ready
degraded
failed
blocked
```

Provider/domain adapters translate their native status into this common vocabulary.

## Ownership

Observed resources use:

```text
synthran
operator
other
unknown
unowned
```

Ownership meaning depends on the operation policy rather than being a blanket permission flag.

`Observation.permits_automatic_mutation()` is intentionally strict: only a fresh live `synthran`-owned observation satisfies that helper for automatic mutation of an existing resource.

Other policy paths may deliberately allow a different reviewed scope. In particular, the current R3 application teardown policy accepts fresh `synthran` **or** `operator` ownership, rejects `other` and `unknown`, requires an exact resource ID for every targeted non-absent resource, and binds those exact IDs into the destructive operation plan. Authorization recomputes that target scope before an `ExecutionPermit` can be issued.

That R3 planning rule still does not make a local observation sufficient provider cleanup authority. A future concrete teardown executor must perform its final live provider checks and may act only within the exact authorized target set.

An absent resource can be `unowned`; that can permit a later approved create/acquisition operation after the required provider authority and resource-decision checks.

## Persisted snapshot

A reconciled application snapshot is stored as:

```text
.synthran/experiments/<experiment-id>/observed.json
```

It records the selected observation for each collected dimension at persistence time and can be replaced as newer observations arrive.

Persisting the snapshot does not change source authority. A cached copy of a provider result becomes historical when its freshness boundary passes.

A separate `status.json` may be written by the lower-level `WorkspaceSession` helper for its compact provider-experiment summary. That file is not the `ApplicationController` observed-state model.

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

`PATH_PROVEN` requires a current path observation. Historical successful evidence remains valid provenance but does not claim that the current network is still usable.

`EXPERIMENT_RUNNING` requires a current experiment observation with `running=true`.

A current critical failure yields `RECOVERY_REQUIRED`. A current explicit block yields `BLOCKED`.

## Fail-closed network reconciliation

`plan_reconciliation()` is pure. It does not execute shell commands or provider mutations. It emits only the next safe boundary.

A representative sequence is:

```text
inspect controller / project / provider experiment
inspect reservation
reserve if absent
inspect allocation
allocate if absent
check physical-radio lease when required
inspect preparation
prepare if absent
inspect network runtime
up when required components are absent
verify-path when network runtime is ready but the path is not currently proven
```

The planner stops when an earlier dependency is unknown/blocked. It never skips an inspection and mutates a later resource based on assumptions.

Examples:

- unknown reservation -> `inspect-reservation`, no mutation;
- absent reservation -> R2 `reserve` step;
- foreign/unknown allocation ownership -> block;
- incomplete SynthRAN-owned allocation -> R2 `recover-allocation` step;
- incomplete non-SynthRAN-owned allocation -> block;
- physical radio without an active R2Lab lease -> `obtain-r2lab-lease` external/read-only requirement;
- prepared resources with absent required network components -> R2 `up` step;
- ready network without current path proof -> R1 `verify-path` step.

## Application workflow policy

Experiment/evidence/log/teardown operations are evaluated separately by `synthran.app.workflows` and then handed to the same operation engine.

Those policies include additional current-state requirements, such as:

- current controller/project/provider-experiment authority;
- `PATH_PROVEN` before experiment start;
- current running experiment before stop;
- relevant runtime state before component-log access;
- exact fresh ownership/resource IDs before R3 teardown.

This separation prevents network reconciliation from being stretched into unrelated experiment/destructive policy.

## Risk classes

Policy steps use:

```text
R0  local/read-only inspection or external requirement
R1  non-destructive verification/evidence access
R2  controlled mutation requiring standard approval
R3  destructive mutation requiring destructive approval
```

The current network reconciler does not emit R3. R3 teardown comes from application workflow policy and carries exact target binding.

## Adapter boundary

Provider/domain code is responsible for producing observations without redefining the truth hierarchy.

Examples include:

- SLICES/controller adapters for project/provider-experiment/resource facts;
- POS/SLICES resource observations for reservation/allocation/preparation;
- Kubernetes/runtime observations for core/RAN/UE/service state;
- network verification for PDU/UPF/path facts;
- R2Lab observations for lease/radio/UE hardware state.

The terminal consumes the reconciled common model. It must not duplicate provider-specific status logic or promote raw provider text directly into trusted state.
