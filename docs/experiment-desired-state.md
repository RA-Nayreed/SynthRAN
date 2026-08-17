# Experiment desired-state contract

SynthRAN keeps requested network configuration separate from provider-assigned runtime observations.

Every fully configured experiment contains:

```text
.synthran/experiments/sran-YYYYMMDD-NNN/
├── experiment.toml
├── desired.json
├── status.json
├── providers/
├── operations/
├── runs/
├── evidence/
└── datasets/
```

`experiment.toml` is the immutable experiment identity record. `desired.json` is the complete requested network configuration. `status.json` and provider evidence describe what was actually observed.

A runtime-assigned address, pod, allocation, reservation, lease, or interface never becomes desired configuration merely because it was observed once.

## Intent and implementation

The desired-state document can describe the experiment at two levels at the same time:

- high-level intent, such as `virtual-5g`, `physical-5g`, `open-ran`, or `iot-to-5g`;
- optional implementation pins for advanced operation.

Implementation values default to `automatic`. A terminal interface can therefore begin with intent and disclose implementation controls only when requested.

Supported core choices are currently:

- `automatic`;
- `open5gs`;
- `oai`;
- `free5gc`.

Supported RAN choices are currently:

- `automatic`;
- `srsran`;
- `oai`;
- `ueransim`.

Supported UE choices are currently:

- `automatic`;
- `srsue`;
- `oai`;
- `ueransim`.

These are desired implementation constraints, not proof that a deployment exists.

## Core and service addressing

Core desired state contains:

- enabled/disabled;
- implementation;
- Kubernetes namespace;
- NRF address policy;
- optional static NRF address.

NRF addressing has two policies:

```text
discover
static
```

With `discover`, an NRF service or load-balancer address is runtime state and is not stored in the desired document. With `static`, the operator intentionally requests a particular valid IP address and that address is part of desired state.

This distinction applies generally: addresses produced by Kubernetes, a UE PDU session, SLICES, POS, or R2Lab are observations unless the experiment explicitly requests a static value.

## RAN topology

RAN desired state includes:

- enabled/disabled;
- implementation;
- namespace;
- architecture;
- gNB ID;
- F1;
- E1;
- DU presence.

Architectures are:

```text
automatic
monolithic
cu-du
cu-cp-up-du
```

Validation rejects contradictory configurations. A monolithic RAN cannot request F1/E1. A CU/DU topology requires a DU and F1. A CU-CP/CU-UP/DU topology also requires E1.

## UE configuration

UE desired state contains:

- enabled/disabled;
- implementation;
- namespace;
- requested UE count.

Assigned PDU addresses and observed UE tunnel interfaces are not stored here. They are discovered during reconciliation and verification.

## Radio capability

Radio desired state separates intent from exact hardware:

```text
mode       automatic | virtual | physical
backend    automatic | rfsim | r2lab
hardware   automatic | n300 | n320
```

Normal guided use can leave backend/hardware automatic. Exact hardware pinning remains available for research cases that require it.

Validation prevents impossible combinations such as a virtual radio with R2Lab or N300/N320 hardware, and a physical radio with RFSIM.

## PLMN and tracking area

The experiment defines:

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

Host addresses such as `12.1.1.1/24` are rejected when a network prefix such as `12.1.1.0/24` is required.

## Slices and QoS

Every experiment configures at least one slice. A slice contains:

- SST;
- optional six-hex-digit SD;
- DNN reference;
- 5QI;
- uplink AMBR in bits per second;
- downlink AMBR in bits per second;
- optional per-slice PLMN override.

S-NSSAI values must be unique and every slice DNN must reference a configured DNN.

Rates are stored as integer bits per second rather than display strings such as `200Mbps`. Interfaces may render human-readable units, but persistence remains unit-explicit and unambiguous.

## Multus and RIC

Multus desired state contains:

- enabled/disabled;
- optional network-attachment name;
- optional host-interface name.

RIC desired state currently supports FlexRIC and can be enabled or disabled.

## Placement

Placement is either `automatic` or `manual`.

Automatic placement cannot contain pinned resources. The resource resolver is responsible for selecting a compatible deployment node, core node, RAN node, and any additional required capabilities.

Manual placement may pin:

- deployment node;
- core node;
- RAN node;
- extra resource names.

Manual pins are constraints. They do not give SynthRAN permission to take over resources. Live ownership and availability checks still govern reservation/allocation operations.

## Issuance and persistence

`create_desired_experiment()` allocates the concrete `sran-YYYYMMDD-NNN` identity first and then stores the complete desired document. If desired-state persistence fails, that experiment ID is marked failed and remains consumed.

Replacing an existing `desired.json` requires an explicit replace operation. Silent overwrite is not allowed.

The immutable experiment identity summary and detailed desired document must agree on experiment intent and radio mode.

## Guided terminal use

The intended terminal interaction is progressive rather than a long deployment form.

A normal user can provide intent such as:

```text
Create a physical 5G testbed
```

and accept a recommended desired state. Advanced configuration can expose core/RAN implementation, split topology, NRF policy, PLMN, DNNs, slicing/QoS, Multus, RIC, radio hardware, and manual placement.

Both interfaces produce the same validated `ExperimentDesiredState`. The UI is therefore not a second deployment implementation.

## Reconciliation boundary

The desired document answers:

```text
What network did the researcher request?
```

Live providers answer:

```text
What exists now?
```

A later reconciler compares the two and emits an operation plan. Resource mutation is allowed only after current ownership, provider authority, reservation/lease, compatibility, and operation policy checks pass.
