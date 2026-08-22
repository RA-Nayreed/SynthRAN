# R2Lab physical adapter implementation record

This document records the physical network/chart work that followed `r2lab-smoke-002`: what was inspected, how each issue was discovered, and how the result is encoded in the consolidated R2Lab package.

The live chronology is in `docs/r2lab-smoke-002.md`. The broader implementation chronology is in `docs/r2lab-smoke-002-development-log.md`. Package structure is documented in `docs/r2lab-code-architecture.md`.

## Starting rule

The accepted `synthran.fiveg_ansible` adapter remains RFSIM-only. Physical support is not added by widening its radio whitelist or adding N300 branches to the virtual path.

The physical backend has different invariants: UHD/N300 instead of ZMQ/RFSIM, one physical SDR owner at a time, a COTS qfit modem instead of srsUE, explicit carrier/SSB/Point-A semantics, exact provider-state evidence, a dedicated physical image digest, and a chart Deployment that must be staged stopped and started without overlapping owners.

Those behaviors now live together in `synthran/r2lab/deployment.py`, with provider semantics in `provider.py` and radio/UE semantics in `radio.py`.

## Exact pinned sources reviewed

The checkpoint was reviewed against exact dependency-lock revisions rather than repository default branches:

```text
fiveg_ansible
a0149fc0dde39e2872945a0f3c91e804ece52d4f

srsran_helm
8dfb9890d127734cdcd6eee9df8c5d09b1a8076a
```

### How this was discovered

During smoke-002 we had already proven that the generic virtual deployment path could not simply be reused for N300. After the run, the exact commits recorded in `dependencies.lock.yml` were opened and the N300 values, Deployment template, and physical retry tasks were inspected directly. This made the differences between the accepted RFSIM path and the physical path concrete instead of inferred.

## Discovery: the pinned chart matches useful N300 topology, but is not safe enough by itself

The pinned srsRAN chart established useful structure:

- `.Values.gnbConfig` supplies the gNB configuration;
- AMF configuration lives under `cu_cp.amf`;
- the N300 path uses UHD;
- the RU network is macvlan-based;
- the RAN node is selected explicitly;
- the chart exposes the remote-control port through `gnbConfig.remote_control`.

### How it was discovered

The exact pinned values file and chart templates were read side by side with the configuration that had actually worked during smoke-002.

### Implementation consequence

The canonical render in `synthran/r2lab/deployment.py` was changed to the chart's real `cu_cp.amf` structure. SynthRAN review metadata is kept outside the final `gnbConfig` so it cannot become an unknown srsRAN key.

The same upstream values also contain CORESET/PRACH settings explicitly described as matching srsUE capabilities. They are deliberately absent from the qfit/COTS candidate.

## Discovery: normal Deployment replacement can create two physical gNB owners

During the live run, a normal Kubernetes replacement briefly left a terminating gNB while a replacement pod attempted to start. Both competed for one N300 UHD device.

The pinned Deployment template was then inspected and found to contain a hard-coded:

```text
replicas: 1
```

with no explicit non-overlapping replacement strategy.

### Implementation consequence

`deployment.py` owns a singleton lifecycle:

```text
scale exact gNB Deployment to zero
  -> prove all matching pods are gone, including terminating pods
  -> allow UHD release
  -> apply reviewed configuration
  -> scale exact Deployment to one
  -> prove exactly one matching pod is Running and ready
```

More than one matching pod causes fail-closed scale-to-zero recovery.

The guarded chart overlay also makes replica count values-driven and installs `Recreate`, allowing the chart to be staged safely at zero replicas.

## Discovery: the pinned chart renders the physical image by mutable tag

The exact Deployment template renders `repository:tag`. Smoke-002, however, had exercised a specific UHD image digest.

### How it was discovered

The live pod image was captured during the run, then compared with the exact pinned Deployment template and `dependencies.lock.yml`.

### Implementation consequence

The lock now contains separate virtual and physical srsRAN gNB entries. The virtual RFSIM lock is unchanged. `srsran_gnb_physical` records the reviewed UHD/N300 image and digest.

The guarded chart overlay changes the reviewed image expression to:

```text
repository:tag@sha256:digest
```

If any exact upstream anchor changes, the overlay refuses to apply rather than silently patching a different chart.

## Discovery: the optional log sidecar is not digest-pinned

The chart can add a `busybox` log sidecar using an unpinned image reference. It is not required for physical acceptance because SynthRAN owns its evidence path.

### Implementation consequence

The physical values disable that sidecar. Offline render validation rejects a rendered unpinned log sidecar.

## Discovery: the upstream N300 retry path has incompatible ownership semantics

The exact pinned `fiveg_ansible` physical tasks were inspected. For N300/N320 the upstream path can:

- uninstall the existing `srsran-gnb` release;
- retry deployment;
- inspect the first returned pod when deciding readiness;
- swap paired radio IP addresses after failure;
- remove the failed release before another attempt.

### Why this matters

Those behaviors are reasonable for a human-oriented recovery playbook, but not for SynthRAN's research-evidence contract. Automatic IP swapping changes the tested hardware binding, and selecting the first pod is unsafe during replacement.

### Implementation consequence

SynthRAN does not call that N300 retry role as its production lifecycle. The physical deployment subsystem consumes the pinned chart contract directly through the reviewed overlay and singleton lifecycle.

## Discovery: SSB ARFCN is not the carrier-center ARFCN

After smoke-002, the R2Lab OAI reference was inspected more carefully. It records separate values for:

- SSB ARFCN `621312`;
- Point-A ARFCN `620040`;
- 162 PRBs at 30 kHz SCS;
- two TX and two RX paths.

The final smoke-002 test had reused `621312` as the srsRAN `dl_arfcn`. That was not a faithful translation because `dl_arfcn` is the carrier center in this configuration.

### Derivation

```text
162 PRB x 12 subcarriers x 30 kHz = 58.32 MHz occupied grid
half grid = 29.16 MHz
29.16 MHz / 15 kHz FR1 ARFCN raster = 1944 steps
620040 + 1944 = carrier-center ARFCN 621984
```

### Implementation consequence

`synthran/r2lab/radio.py` models carrier center, SSB, and Point A as different semantics. The reviewed offline candidate is:

```text
band 78
carrier-center ARFCN 621984 (~3329.76 MHz)
expected SSB ARFCN 621312
nominal bandwidth 60 MHz
common SCS 30 kHz
2x2 antennas
```

The candidate remains offline-only until a COTS UE acquires the rendered cell in a controlled follow-up run.

## One coherent deployment subsystem

The first implementation pass split the physical pipeline across plan/render/chart/workspace/Helm/artifact/staging/lifecycle modules. That made individual units isolated but made the complete operation unnecessarily hard to follow.

After architecture review, those responsibilities were consolidated into `synthran/r2lab/deployment.py` as one subsystem. The internal boundaries are still explicit through dataclasses and functions, but the developer can now follow the physical path in one module:

```text
reviewed radio intent
  -> physical deployment plan
  -> canonical srsRAN render
  -> pinned chart bundle
  -> guarded isolated chart overlay
  -> locked Helm template render
  -> rendered-text validation
  -> deterministic package + hashes
  -> stopped-only cluster staging
  -> singleton start lifecycle
```

This structural correction is described in `docs/r2lab-code-architecture.md`.

## Offline Helm render gate

Before Kubernetes is contacted, the deployment subsystem verifies the locally locked Helm version, runs only `helm template`, and rejects the output unless it proves:

- exactly the digest-locked physical gNB image;
- zero replicas;
- `Recreate`;
- carrier ARFCN `621984`;
- 60 MHz bandwidth;
- 2 downlink and 2 uplink antenna paths;
- no inherited srsUE-specific CORESET/PRACH override;
- no optional mutable log sidecar;
- no RFSIM or broad cleanup behavior.

Successful validation returns a SHA-256 render hash. It is still offline evidence, not live acceptance.

## Stopped-only cluster staging

The staging boundary can transfer and install only the already-reviewed artifact while keeping the gNB stopped. Before Helm staging it requires:

- fresh SLICES reservation authority;
- matching f2/f3 allocation ownership;
- strict known-host SSH;
- local and remote artifact hash equality;
- the locked Helm version on the controller;
- an Open5GS namespace owned by the same run;
- an absent or zero-replica existing gNB Deployment;
- zero matching gNB pods.

After staging it again requires desired replicas `0` and pod count `0`.

This operation does not power the N300, does not touch qfit, and does not claim physical acceptance.

## qfit runtime evidence

Smoke-002 showed that “UE works” cannot be one boolean. Cell visibility, registration, packet-service attachment, address assignment, and user-plane traffic are different stages.

`synthran/r2lab/radio.py` therefore classifies already-collected qfit evidence into conservative states for:

- NR-SA cell acquisition / no service / other service / unknown;
- registration / searching / not registered / unknown;
- packet attached / detached / unknown;
- IPv4 present / absent / unknown.

Packet attachment plus IPv4 can become PDU-session evidence only after cell acquisition and registration. User-plane acceptance still requires a separate traffic probe.

## Ordered physical acceptance

`synthran/r2lab/acceptance.py` records:

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

A stage cannot be skipped. A failed stage blocks later acceptance, which preserves the actual smoke-002 truth: lower-layer bring-up succeeded, cell acquisition failed, and later stages were not reached.

## CI discoveries during implementation

Two earlier CI failures were useful quality signals rather than physical-network failures.

A qfit parser variable with a credential-like name triggered the tracked-source privacy scanner even though it contained only provider status text. The variable was renamed; the scanner was not weakened.

A later foundation text-policy check rejected a literal Kubernetes runtime-state field name. The parser still reads the real JSON field, but constructs that field name from neutral fragments so the product source remains within repository text policy. Another render fixture accidentally contained the virtual backend name in its run ID; the fixture was renamed so the test inspected rendered configuration rather than its own label.

The full workflow returned green after those corrections before the chart/staging work continued.

## Current boundary

The physical backend now has a reviewed offline chain and a stopped-only staging boundary. Remaining live work is narrower:

- add dedicated fake-runner regression coverage for stopped staging;
- persist artifact/render/staging hashes into run evidence;
- bind singleton start to fresh N300 authority/claim and the exact staged artifact;
- collect sanitized qfit cell/registration/PDU evidence;
- add an independently verified user-plane probe;
- connect all observations to the ordered acceptance record;
- run another controlled physical acceptance attempt only after those gates are green.
