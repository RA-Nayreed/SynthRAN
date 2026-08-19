# SynthRAN Repository Instructions

## Purpose

SynthRAN is a reproducible experiment-control platform joining deterministic IoT emulation, an open 5G user plane, and research-grade evidence.

The accepted virtual path is:

```text
10 Contiki-NG/Cooja sensors
-> RPL / 6LoWPAN
-> tunslip6 / tun0
-> counted MQTT ingress
-> Mosquitto bridge in the srsUE network namespace
-> tun_srsue1
-> srsRAN gNB
-> Open5GS UPF
-> run-owned central broker / collector
-> canonical JSONL
-> deterministic Parquet
```

SynthRAN owns orchestration, contracts, integration adapters, validation, evidence, cleanup, and reproducibility reporting. It does **not** reimplement Open5GS, srsRAN, Contiki-NG, Cooja, Mosquitto, iperf3, or SLICES provider services.

For current live evidence, use [`docs/results.md`](docs/results.md). Do not duplicate a competing list of “latest” run IDs across documentation.

## Integration truth

`main` is the integration truth. Before substantial work, inspect current code, tests, and current documentation rather than relying on an older PR, chat transcript, or historical result note.

Development history is not product architecture. Public commands, schemas, filenames, and statuses must describe durable concepts, not temporary implementation milestones.

There is one product executable:

```text
synthran
```

- no arguments: `prompt_toolkit` interactive terminal;
- explicit arguments: scriptable CLI.

The interfaces are not yet identical execution paths. The terminal goes through the persistent application/operation control plane. The scripted CLI still invokes established network, experiment, research, and R2Lab executors directly. Never make the terminal secretly invoke the CLI just to make a command appear implemented.

## Terminal contract

The terminal registry is authoritative:

```text
/status
/inspect resources|network
/reserve
/up
/verify
/recover
/down
/run baseline|congestion
/stop
/collect
/logs network|open5gs|ue
/config resources|experiment
/mode observe|operate
/help
/clear
/quit
```

A session starts in OBSERVE mode. OPERATE permits mutating requests to reach policy; it is not approval. Normal plan, approval, freshness, ownership, concurrency, and executor checks still apply.

Current provider-facing terminal workflows are planning-first:

```text
slash command
-> TerminalSession
-> ApplicationController
-> reconciliation/workflow policy
-> immutable OperationPlan
-> approval / authorization
-> ExecutionPermit
-> provider/domain executor   # not yet connected for terminal workflows
```

A rendered `Execution: not started` means exactly that. Do not describe it as a reservation, deployment, experiment execution, collection, log read, or teardown.

## State and reconciliation invariants

Requested intent and discovered facts remain separate:

- `ExperimentDesiredState`: declared intent and stable constraints;
- `ObservedState`: discovered provider/runtime facts.

PDU addresses, pod names, reservation/allocation identifiers, current lease state, and similar dynamic values are observed facts, never desired state.

Observed-state truth ranking is:

```text
provider
> direct observation
> persisted evidence
> manifest
> cache
```

Only fresh provider/direct observations may authorize current provider mutation. Historical evidence proves what happened; it does not become current authority.

`plan_reconciliation()` is pure and emits only the next safe boundary. Unknown, stale, foreign, expired, failed, or ambiguous ownership fails closed.

Current lifecycle values include:

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

Experiment/evidence/log/teardown workflows remain separate from network reconciliation and still pass through `OperationController` after policy evaluation.

## Operation control

Operation plans bind current desired state, observed state, policy/reconciliation state, exact targets, and relevant input digests.

Risk classes are:

```text
R0  local/read-only
R1  live/read-only verification or evidence access
R2  controlled mutation requiring approval
R3  destructive mutation requiring destructive approval
```

Authorization rechecks policy and state before issuing an `ExecutionPermit`. Only one mutation may hold the workspace mutation claim. If a mutation fails or is interrupted and clean rollback cannot be proven, preserve the claim and enter recovery-required state.

Structured `OperationEvent` records are the trusted progress surface. Never infer operation state by parsing terminal prose or arbitrary provider stdout.

## Resource and provider safety

Resource selection must be deterministic and based on reviewed descriptors plus fresh complete provider inventory.

Generic rollback authority comes only from exact resources proven to have been created by the current operation. Roll back in reverse acquisition order. Never guess provider ownership from naming conventions.

Never use broad cleanup such as `pkill`, `killall`, wildcard resource deletion, or guessed reservation/allocation IDs when an exact run-owned target is required.

Provider experiment creation remains an explicit operator action. SynthRAN may bind to an existing SLICES experiment but does not silently log in, switch projects, or create provider experiments.

## Live-accepted research boundary

The supported virtual configuration is deliberately narrow:

- core: Open5GS;
- RAN: srsRAN;
- radio: RFSIM;
- UE: one srsUE acting as the IoT edge gateway;
- one SST-1 slice with DNN `internet`;
- exactly ten deterministic Cooja sensors;
- UDP for controlled research load;
- JSONL as append-only audit data and deterministic Parquet as its derivative.

Current accepted research evidence is summarized in [`docs/results.md`](docs/results.md). As of the accepted campaign there is a complete 12-run blocked dataset across baseline, 50%, 80%, and 95% background-load conditions. Do not restore stale claims that valid loaded evidence is still pending.

Physical RF, multiple UEs/slices, TCP research load, formal A1/E2/RIC integration, generative models, synthetic telemetry, and automated RAN-policy synthesis remain unproven unless later accepted evidence explicitly changes that status.

## Research measurement peer invariant

Capacity calibration and controlled background load must terminate **outside the 5G core host**.

For the supported two-node virtual inventory:

```text
UE PDU
-> tun_srsue1
-> 5G user plane
-> Open5GS UPF
-> core egress / NAT
-> prepared RAN node (measurement peer)
```

The core node is explicitly rejected as the iperf3 measurement server because a same-host target can collapse into a Kubernetes/hairpin path.

The run-owned iperf lifecycle must preserve all of these properties:

- server startup, ownership proof, stale recovery, and cleanup occur on the selected external peer;
- the supplied target is proven assigned to that peer;
- the UE client binds its live PDU and uses the exact route through `tun_srsue1`;
- loaded readiness requires an actual `ESTABLISHED` iperf3 TCP control connection while UDP data is active;
- `CLOSE-WAIT` is never accepted as readiness;
- same-host/core-target calibrations remain diagnostic evidence only.

See [`docs/research-measurement-peer.md`](docs/research-measurement-peer.md).

## Research data semantics

Do not confuse observation-window occupancy with packet loss.

The v1alpha1 telemetry summary contains a fixed nominal expected count computed from `duration / sensor_period`. A periodic sensor can legitimately contribute one fewer record when the exact measurement-window boundaries fall between transmissions. Therefore:

- `delivery_ratio` in existing v1alpha1 summaries is a **nominal window-coverage metric**;
- observed sequence gaps and duplicates are the primary integrity evidence for packet/event continuity;
- never describe a shorter but contiguous sequence range as observed packet loss merely because it contains fewer records than the nominal count.

Campaign-06 contained zero sequence gaps and zero duplicates across all accepted runs. The detailed evidence and interpretation boundary are in `docs/results.md`.

Network sampling has a separate timing contract. A requested interval is not proof that the sampler achieved that cadence. Persisted `sample_duration_seconds` and `schedule_lag_seconds` are measurement evidence. Future runs must fail closed when achieved counter-sampling cadence falls materially below the requested rate.

The campaign-06 counter sampler achieved approximately one sample every three seconds despite a one-second request; this limitation is public evidence and must not be rewritten as 1 Hz sampling. The run-level counter deltas remain valid for their measured interval.

## Experiment validity

A research result may enter campaign analysis only when its own persisted validity gates pass. Keep these concepts distinct:

- base-network path acceptance;
- integrated IoT-path acceptance;
- external-peer calibration validity;
- current measurement-path validity;
- load-target validity;
- instrumentation validity;
- cleanup/base-network reproof;
- scientific interpretation.

Zero telemetry is not automatically a network result. Conversely, a telemetry sequence loss may be a legitimate scientific outcome if independent path/load/instrumentation validity remains healthy. Do not encode the desired scientific result into infrastructure validity gates.

Failed and invalid runs remain immutable diagnostic evidence and must never be silently reclassified or reused under the same run ID.

## Reproducibility and preservation

Pinned upstream checkouts live below ignored `.deps/` storage. Do not vendor or partially copy upstream projects merely for convenience. Keep selected runtime images digest-pinned and preserve third-party license/provenance records.

Research artifacts should preserve the immutable run specification, measurement window, telemetry, RTT probes, network counters, load records, validity summary, and artifact digests. Raw campaign evidence belongs in durable research/object storage; small derived public analyses may be tracked under `results/`.

Checksum manifests must never include an entry for the manifest file itself. The historical campaign-06 preservation archive contains that known self-reference bug; the archive-level S3 SHA-256 remains the canonical frozen integrity check and the object must not be rewritten.

## Credentials and privacy

Never commit:

- subscriber credentials;
- SLICES tokens or S3 secrets;
- private SSH keys;
- kubeconfigs;
- private authority/environment files;
- unsanitized packet captures or secret-bearing logs;
- generated live run directories;
- dependency worktrees.

Privacy protections are layered through ignore rules, repository scanning, pre-push checks, CI, and GitHub controls. Do not weaken a privacy rule merely to make a check pass.

Prefer route proof, counters, broker receipt, and message-integrity evidence over packet capture when they prove the required boundary with lower privacy risk.

## Documentation discipline

Public documentation has distinct jobs:

- `README.md`: explain SynthRAN to a new reader;
- `docs/results.md`: canonical current live evidence and scientific interpretation boundary;
- `docs/experiment.md`: experiment/research protocol and validity rules;
- `docs/architecture.md`: durable system boundaries;
- `docs/operator-guide.md`: commands an operator actually runs;
- historical result files: immutable engineering history, not current capability truth.

Do not turn the README back into an operator manual or changelog. Link to detailed docs instead of copying large sections between files.

## Validation before completion

From the repository root in the `synthran` environment, run applicable checks:

```bash
python -m unittest discover -s tests -v
python -m synthran privacy scan --worktree
git diff --check
git status --short
```

When history secret scanning is available, run it as well.

Before merging, inspect the complete intended diff and confirm:

- docs describe current code and accepted evidence, not desired future behavior;
- planning is not described as provider execution;
- current and historical evidence are not mixed;
- no private credentials/evidence were added;
- measurement limitations are stated rather than hidden;
- scientific observations are not promoted into causal claims without sufficient replication;
- new mutation or cleanup behavior remains exact, ownership-bound, and fail-closed.
