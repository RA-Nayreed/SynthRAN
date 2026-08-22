# R2Lab integration branch

## Branch model

`r2lab-integration` is the temporary integration main for physical R2Lab work while `main` remains the accepted RFSIM truth. Physical checkpoints merge into `r2lab-integration` first; `main` is not advanced until physical acceptance is complete.

The current checkpoint is `r2lab-smoke-gate`. The already-open pull request retains its historical remote head name until that PR is complete, but new branch names, documentation, and plans use the `r2lab-*` convention without the old prefix.

```text
main                         accepted RFSIM truth
  |
  +-- r2lab-integration      temporary physical-integration main
        |
        +-- r2lab-smoke-gate current PR/checkpoint
        +-- r2lab-*          future physical checkpoints
```

## Current physical truth

The accepted virtual Open5GS + srsRAN + srsUE + RFSIM path remains unchanged.

`r2lab-smoke-002` established live evidence for:

- active R2Lab authority and exact-resource control;
- SLICES/POS preparation and a two-node Kubernetes foundation;
- Open5GS core deployment;
- an N300-backed srsRAN gNB;
- gNB-to-AMF N2/SCTP establishment;
- managed qfit07 reachability and modem preparation;
- exact qfit, gNB, N300, core, and namespace cleanup.

It did **not** establish:

- UE cell acquisition;
- 5G registration;
- PDU session;
- UE user plane;
- the full SynthRAN physical workload.

The qfit modem remained in searching/no-service state and the active scans returned no cells for the three configurations transmitted during that run. Post-run inspection also showed that the final test had reused an OAI SSB ARFCN as an srsRAN carrier-center ARFCN, so smoke 002 is not evidence that the R2Lab RF path itself is defective.

## Package architecture

The first implementation pass over-applied one-concern-per-file decomposition and produced 18 flat `r2lab_*` implementation modules under `synthran/network/`. That structure has been corrected.

The implementation now lives in one cohesive package:

```text
synthran/r2lab/
  __init__.py
  controller.py
  provider.py
  radio.py
  deployment.py
  acceptance.py
```

`synthran/network/r2lab.py` remains only as the stable compatibility import used by existing CLI/callers.

The architecture and the reason for the consolidation are recorded in `docs/r2lab-code-architecture.md`.

## Implemented safety semantics

### Provider state

Exact provider observation is the state truth. The live N300 cleanup demonstrated that `rhubarbe pdu off n300` can return status 1 while the provider reports `OFF`. Mutation and status return codes are therefore diagnostic evidence; the exact selected-resource state decides whether a transition is accepted.

A mutation timeout does not imply no mutation. The controller still issues the exact provider-state query after a mutation transport failure. Missing or contradictory evidence remains unknown.

### Claims and cleanup

A workspace claim is removed only when every selected physical resource is proven clean. An unresolved UE cleanup does not trigger global cleanup and does not prevent an independently authorized exact N300 cleanup. `all-off` and broad `rhubarbe bye` remain forbidden.

### qfit

qfit resources use their own provider path. `qfit on|off qfitNN` is followed by independent `rhubarbe status N` verification. qfit state is not inferred from the helper return code.

### Physical gNB ownership

An N300 is a singleton hardware owner. The physical lifecycle therefore performs:

```text
scale exact gNB deployment to zero
  -> prove zero matching pods, including terminating pods
  -> allow UHD release
  -> apply reviewed configuration
  -> scale to one
  -> prove exactly one Running/ready gNB pod
```

Ambiguous startup or overlapping pods requests exact scale-to-zero recovery and fails closed.

### Radio semantics

The reviewed R2Lab OAI reference distinguishes:

- SSB ARFCN 621312;
- Point-A ARFCN 620040;
- 162 PRBs at 30 kHz SCS;
- 2 TX and 2 RX paths.

The offline reference-aligned srsRAN candidate derives carrier-center ARFCN 621984 (~3329.76 MHz), nominal 60 MHz, 30 kHz SCS, and 2x2 antennas. SSB, Point A, and carrier-center ARFCNs are typed separately so they cannot be silently substituted for one another.

This candidate is not live accepted.

## Physical deployment boundary

The physical backend is separate from the accepted RFSIM `fiveg_ansible` adapter.

The R2Lab deployment subsystem now provides:

- a narrow Open5GS/f2 + srsRAN/f3 + N300 deployment plan;
- canonical physical srsRAN values;
- a dedicated digest lock for the UHD gNB image;
- a guarded overlay for the exact pinned srsRAN Helm chart;
- values-driven zero replicas and `Recreate` strategy;
- digest-addressed physical gNB image rendering;
- isolated chart workspace hashing;
- offline `helm template` validation;
- deterministic chart/value packaging;
- strict SLICES authority checks and a stopped-only cluster staging boundary;
- a non-overlapping singleton start lifecycle.

The stopped staging operation is intentionally not a radio start. It requires fresh reservation/allocation authority, strict known-host SSH, a run-owned namespace, matching artifact hashes, the locked Helm version, zero desired replicas, and zero gNB pods. It stages only the reviewed artifact at `replicas=0`.

## Physical acceptance model

Acceptance is ordered:

```text
resource authority
  -> SLICES foundation
  -> Kubernetes
  -> Open5GS
  -> gNB/N2
  -> UE management
  -> cell acquisition
  -> registration
  -> PDU session
  -> user plane
  -> workload
```

Stages cannot be skipped. A failed stage blocks later acceptance and later stages remain explicitly `not-reached`.

## Evidence and development history

Detailed records are maintained in:

- `docs/r2lab-smoke-002.md` — live run chronology and acceptance result;
- `docs/r2lab-smoke-002-development-log.md` — how live observations became code and how CI issues were diagnosed;
- `docs/r2lab-physical-adapter.md` — physical chart/adapter investigation;
- `docs/r2lab-code-architecture.md` — package-consolidation rationale and current subsystem boundaries.

## Remaining work before this checkpoint can merge

The PR remains draft. The main remaining work is:

- add dedicated fake-runner regression coverage for the stopped physical staging controller;
- persist the reviewed artifact/render/staging hashes into the run evidence model;
- bind the singleton gNB start to fresh R2Lab N300 authority/claim and the exact staged artifact;
- implement sanitized qfit probes for cell acquisition, registration, packet-service/PDU state, and user-plane traffic;
- feed those runtime observations into the ordered acceptance record;
- run the complete repository regression suite and privacy checks on the consolidated package;
- perform another controlled physical acceptance run using the reviewed carrier/SSB/bandwidth/2x2 profile.

Do not merge this checkpoint into `r2lab-integration` until those boundaries are green and the follow-up physical run has been reviewed.
