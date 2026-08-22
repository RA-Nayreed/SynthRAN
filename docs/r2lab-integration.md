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

No later code work has changed that live truth. The new physical boundaries are regression-tested but are not live accepted yet.

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
  runtime.py
  ue.py
```

`synthran/network/r2lab.py` remains only as the stable compatibility import used by existing CLI/callers.

The architecture and the reason for the consolidation are recorded in `docs/r2lab-code-architecture.md`.

## Implemented safety semantics

### Provider state

Exact provider observation is the state truth. The live N300 cleanup demonstrated that `rhubarbe pdu off n300` can return status 1 while the provider reports `OFF`. Mutation and status return codes are therefore diagnostic evidence; the exact selected-resource state decides whether a transition is accepted.

A mutation timeout does not imply no mutation. The controller still issues the exact provider-state query after a mutation transport failure. Missing or contradictory evidence remains unknown.

### Claims and cleanup

A workspace claim is removed only when every selected physical resource is proven clean. An unresolved UE cleanup does not trigger global cleanup and does not prevent an independently authorized exact N300 cleanup. `all-off` and broad `rhubarbe bye` remain forbidden.

### qfit provider power

qfit resources use their own provider path. `qfit on|off qfitNN` is followed by independent `rhubarbe status N` verification. qfit provider state is not inferred from the helper return code.

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
- a non-overlapping singleton start lifecycle;
- fresh R2Lab claim/lease/N300 binding at start;
- immutable staged/start artifact hashes.

The stopped staging operation is intentionally not a radio start. It requires fresh reservation/allocation authority, strict known-host SSH, a run-owned namespace, matching artifact hashes, the locked Helm version, zero desired replicas, and zero gNB pods. It stages only the reviewed artifact at `replicas=0`.

## Read-only physical runtime boundary

`synthran/r2lab/runtime.py` now provides the live observation path after the gNB starts:

- current run/artifact-bound gNB/N2 proof;
- current qfit management proof;
- allow-listed cell/registration/packet/IP observation;
- strict nested qfit SSH;
- no `AT+CIMI`, `check-ue`, attach, connect, or `start.sh` in the read-only path;
- immediate reduction of raw output into sanitized categorical evidence;
- optional bounded `wwan0` user-plane proof for an already-established PDU session.

The runtime verifier does not mutate modem, radio power, Helm, or Kubernetes state.

## Controlled qfit activation boundary

`synthran/r2lab/ue.py` now owns the mutating COTS-UE/session path.

The current activation contract is intentionally narrow:

```text
DNN       internet
MBIM      /dev/cdc-wdm0
interface wwan0
session   0
IP type   ipv4
```

The upstream `prepare-ue`, `config-ue`, `check-ue`, `start.sh`, and `stop.sh` wrappers were inspected before implementing this boundary. SynthRAN does not call them directly during acceptance because they combine broader modem preparation, subscriber inspection, reset, attach, or cleanup behavior.

The activation sequence is explicit:

```text
fresh run/N300 authority
  -> current singleton gNB/N2
  -> qfit management
  -> cell acquisition
  -> registration
  -> wwan0 up
  -> software radio on + state proof
  -> packet attach + state proof
  -> MBIM session 0 using DNN internet
  -> IP setup
  -> attached + IPv4 postcondition proof
```

A non-zero mutation return code is diagnostic. The independently observed state decides whether a transition succeeded.

On unresolved activation failure the exact rollback is software-radio off plus `wwan0` down. Cleanup is accepted only when radio-off, packet-detached, and no-IPv4 observations are all proven. Otherwise activation evidence remains `failed-unresolved`.

The active orchestrator intentionally does not mark a detached registered UE as a failed PDU session before attach has actually been attempted.

## Physical user-plane and workload handoff

After PDU acceptance, the new user-plane entry point refreshes R2Lab authority, singleton gNB/N2, qfit management, and current PDU state before executing the existing bounded `wwan0` traffic proof.

After user-plane acceptance, `execute_physical_workload_handoff()` provides an explicit physical-only handoff. It does not silently call the accepted virtual integrated-experiment runtime.

This separation is required because the current virtual workload implementation is coupled to:

```text
srsUE Deployment ownership
RFSIM reconciliation
tun_srsue1
MQTT sidecar injection into the srsUE pod
```

Those assumptions are not valid for a COTS qfit UE.

A physical workload result must identify `backend=r2lab`, `interface=wwan0`, the matching run ID, a sanitized evidence digest, acceptance state, and cleanup proof. A virtual/RFSIM result cannot satisfy the physical `workload` acceptance stage.

## Physical acceptance model

Acceptance remains ordered:

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
- `docs/r2lab-runtime-verification.md` — read-only qfit/N2 observation design;
- `docs/r2lab-ue-activation.md` — mutating qfit activation, rollback, and workload-handoff design;
- `docs/r2lab-code-architecture.md` — package-consolidation rationale and current subsystem boundaries.

## Remaining work before this checkpoint can merge

The PR remains draft. The implementation boundary is now largely complete offline. Remaining acceptance work is:

- keep the complete repository unit/privacy workflow green on the current head;
- build a physical-specific workload executor behind the new handoff contract rather than reusing the RFSIM experiment runtime;
- perform another controlled physical acceptance run using the reviewed carrier/SSB/bandwidth/2x2 profile;
- verify cell acquisition and registration before invoking the new qfit activation boundary;
- verify PDU session and `wwan0` user plane;
- run the physical workload through the explicit handoff;
- perform and review exact cleanup evidence.

Do not merge this checkpoint into `r2lab-integration` until those boundaries are green and the follow-up physical run has been reviewed.
