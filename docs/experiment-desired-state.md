# Experiment desired-state contract

SynthRAN keeps requested experiment/network configuration separate from provider-assigned runtime observations.

## Persistence

A persistent new-format experiment has a durable identity record and a separate detailed desired-state document:

```text
.synthran/experiments/sran-YYYYMMDD-NNN/
├── experiment.toml
├── desired.json
├── observed.json        # only after application observations are persisted
├── status.json          # optional legacy WorkspaceSession/provider summary
└── runs/                # created when new-format runs are issued
```

`experiment.toml` is the durable issued experiment identity/binding record. `desired.json` is the complete validated requested state used by `ApplicationController` and policy.

`observed.json` is the reconciled application observation cache. A separate `status.json` may be written by the lower-level `WorkspaceSession` helper. Neither file is desired state or permanent mutation authority.

Runtime-assigned addresses, pods, allocations, reservations, leases, resource IDs, or interfaces never become desired configuration merely because they were observed once.

## Intent and implementation constraints

The desired-state model can express both high-level experiment intent and optional implementation constraints.

Supported model values include multiple core/RAN/UE implementations even when the current live-accepted golden path supports only a narrower subset. A value being valid in `ExperimentDesiredState` is **not** proof that its full deployment/provider executor is live accepted.

Current model core choices include:

```text
automatic
open5gs
oai
free5gc
```

Current model RAN choices include:

```text
automatic
srsran
oai
ueransim
```

Current model UE choices include:

```text
automatic
srsue
oai
ueransim
```

The current accepted virtual live path is Open5GS + srsRAN + srsUE + RFSIM.

## Core and service addressing

Core desired state contains requested implementation/service configuration, including NRF address policy.

NRF addressing supports:

```text
discover
static
```

With `discover`, a provider/service-assigned NRF address remains runtime observation. With `static`, the operator explicitly requests a valid address and that value is part of desired state.

The same rule applies generally: provider/Kubernetes/UE-assigned addresses are observed state unless the desired-state schema explicitly models a static requested value.

## RAN topology

RAN desired state models implementation plus requested topology/split constraints, including gNB identity and F1/E1/DU requirements.

Architectures are:

```text
automatic
monolithic
cu-du
cu-cp-up-du
```

Validation rejects contradictory combinations. For example, a monolithic RAN cannot require split interfaces, while split topologies require their corresponding DU/F1/E1 structure.

These values express desired constraints; they do not claim current live acceptance for every topology.

## UE configuration

UE desired state contains requested enablement, implementation, namespace, and UE count.

Assigned PDU addresses and live UE tunnel interfaces are observations and do not belong in desired state.

The current live-accepted golden path uses one srsUE as the IoT edge gateway. Multiple-UE live acceptance remains deferred.

## Radio capability

Radio desired state separates mode, backend, and optional hardware intent:

```text
mode       automatic | virtual | physical
backend    automatic | rfsim | r2lab
hardware   automatic | n300 | n320
```

Validation prevents contradictory combinations such as virtual + R2Lab hardware or physical + RFSIM.

A valid physical/R2Lab desired state is not evidence that physical radio operation has been live accepted. Physical radio acceptance remains separate from desired-state model support.

## PLMN and tracking area

The desired experiment defines:

- MCC, exactly three digits;
- MNC, two or three digits;
- TAC, a 24-bit integer.

Individual slices may optionally override MCC/MNC when both values are supplied.

## DNNs and PDU session types

Every experiment configures at least one DNN. DNN names are unique.

A DNN contains:

- name;
- PDU session type (`ipv4`, `ipv6`, or `ipv4v6`);
- canonical IPv4 and/or IPv6 network prefixes appropriate for that session type.

Where the schema requires a network prefix, host-address CIDRs are rejected.

## Slices and QoS

Every experiment configures at least one slice. A slice contains:

- SST;
- optional SD;
- DNN reference;
- 5QI;
- uplink/downlink AMBR in integer bits per second;
- optional per-slice PLMN override.

S-NSSAI values must be unique and every slice DNN must reference a configured DNN.

Persistence uses explicit integer units rather than display strings such as `200Mbps`.

## Multus and RIC requested state

The desired-state schema can express optional Multus and RIC-related requested constraints.

Model support must not be confused with accepted runtime integration. Formal O-RAN A1/E2 control, general RIC integration, and generative-policy workflows remain deferred in the current product scope.

## Placement

Placement is `automatic` or `manual`.

Automatic placement cannot contain pinned resources. Resource requirements are derived from desired state and resolved against reviewed descriptors plus fresh complete provider inventory.

Manual placement pins are hard constraints, not permission. A pinned resource must still satisfy reviewed capability, current availability, ownership, provider authority, and operation policy.

Runtime allocation results remain observed state and never rewrite desired placement silently.

## Issuance and persistence

`create_desired_experiment()` allocates the concrete `sran-YYYYMMDD-NNN` identity first, persists `desired.json`, and optionally activates the experiment through `.synthran/active.json`.

If desired-state persistence fails after ID issuance, the experiment is marked failed where possible and the ID remains consumed.

Replacing an existing `desired.json` requires an explicit replace operation. Silent overwrite is not allowed.

The durable `experiment.toml` summary and detailed `desired.json` must agree on intent and radio mode.

## Current terminal setup

The strict slash-command shell does not accept natural-language lifecycle requests such as “create a physical 5G testbed.”

When an initialized workspace is `EMPTY`, the production terminal offers a small local setup wizard. It prompts for:

- whether to create an active experiment;
- experiment intent, defaulting to `iot-to-5g`;
- radio mode, defaulting to `virtual`;
- optional existing SLICES provider-experiment binding;
- optional label.

The wizard creates a validated `ExperimentDesiredState` through `ApplicationController.create_experiment()`. It does not reserve/allocate/deploy resources and does not create the provider experiment.

Advanced desired-state fields are available in the Python/domain model, but the current terminal setup wizard does not expose the full model as an interactive deployment form.

## Reconciliation boundary

Desired state answers:

```text
What did the researcher request?
```

Observed state answers:

```text
What is currently known to exist?
```

Reconciliation and application workflow policy compare those models and can produce immutable operation plans. Resource mutation is possible only after current authority/ownership/freshness checks, required approval, authorization, and the concrete executor's final live checks.
