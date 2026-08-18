# SynthRAN Architecture

## Responsibility boundary

SynthRAN is the experiment-control and evidence layer above existing systems. It composes rather than reimplements the underlying 5G, IoT, messaging, and load-generation stacks.

```text
Operator
  |
  +--> synthran                     interactive terminal
  |      |
  |      v
  |    TerminalSession
  |      |
  |      v
  |    TerminalCommandRouter
  |      |
  |      v
  |    ApplicationController
  |      |-- persistent workspace / desired state
  |      |-- observed-state reconciliation
  |      |-- application workflow policy
  |      |-- resource decision binding
  |      `-- OperationController
  |             |
  |             v
  |        ExecutionPermit
  |             |
  |             v
  |        provider/domain executor boundary
  |        (not yet connected for terminal workflows)
  |
  `--> synthran <explicit args>      existing scripted CLI
         |-- SLICES/POS preparation adapters
         |-- 5g_ansible deployment/verification
         |-- R2Lab provider-specific control
         |-- IoT experiment runtime
         `-- controlled research runtime
```

The interactive and scripted interfaces currently share repository models and domain code in several areas, but they are **not yet one identical execution pipeline**. The interactive terminal goes through the persistent application/operation control plane. The existing scripted CLI still invokes established network, experiment, research, and R2Lab executors directly.

The architectural direction is convergence below the interface boundary. The terminal must not invoke the scripted CLI secretly as a shortcut.

Linux is the supported live SynthRAN host platform. Development, repository hooks, GitHub Actions, and live control use the named Conda environment `synthran`. `environment.yml` is the complete supported Linux environment definition; `pyproject.toml` remains package/build metadata and declares the `synthran` executable.

## Product entrypoint

There is one product executable:

```text
synthran
```

The launcher behavior is intentionally simple:

```text
no arguments       -> prompt_toolkit interactive terminal
explicit arguments -> existing scriptable CLI parser
```

The terminal command registry is explicit and accepts only the documented slash commands. It has no natural-language lifecycle fallback and no arbitrary provider/resource override syntax.

See `docs/terminal-commands.md`, `docs/terminal-session.md`, and `docs/terminal-shell.md`.

## Persistent workspace model

The interactive control plane separates long-lived identity, requested experiment state, current observations, and operation records.

```text
~/.config/synthran/profiles/<name>.toml
.synthran/workspace.toml
.synthran/registry.sqlite3
.synthran/active.json
.synthran/experiments/<experiment-id>/desired.json
.synthran/experiments/<experiment-id>/observed.json
.synthran/operations/<operation-id>/...
.synthran/sessions/events.jsonl
```

The registry allocates non-reusable experiment, run, and operation IDs. Filesystem records remain durable provenance and can reconstruct registry counters without reusing issued IDs.

Legacy accepted run/evidence directories may coexist with the new workspace. First-launch adoption preserves those artifacts exactly and fails closed on ambiguous partial new-workspace state.

Initialization is performed by the no-argument terminal when needed. It verifies controller access before local persistence and never reserves, allocates, deploys, powers, or starts an experiment. There is currently no separate top-level scripted `synthran init` command.

## Desired and observed state

Requested intent and discovered facts are separate models.

`ExperimentDesiredState` contains requested choices such as intent, core/RAN/UE family, radio mode, topology, slices, DNNs, QoS/AMBR constraints, placement policy, and optional physical-radio requirements.

Runtime discoveries do not belong in desired state. Provider-assigned resource IDs, PDU addresses, pod names, current lease state, and similar values are observed facts.

The observed-state truth ranking is:

```text
provider
> observation
> evidence
> manifest
> cache
```

Fresh live provider/direct observations can drive current policy. Evidence and manifests preserve historical truth but cannot become current mutation authority after their freshness boundary is gone.

Current lifecycle values are derived from desired plus observed state:

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

See `docs/experiment-desired-state.md` and `docs/observed-state.md`.

## Reconciliation

`plan_reconciliation()` is pure. It produces only the next safe network boundary and never performs a provider command.

A representative progression is:

```text
inspect controller/project/provider experiment
-> inspect reservation
-> reserve if absent
-> inspect allocation
-> allocate if absent
-> verify R2Lab lease when physical radio is requested
-> inspect preparation
-> prepare if absent
-> inspect network runtime
-> up if required network components are absent
-> verify-path if the network is ready but the path is not currently proven
```

The planner stops at the first unresolved authority or dependency boundary. Stale, unknown, foreign, failed, or ambiguous state cannot be skipped merely because older evidence exists.

## Application workflow policy

Experiment, evidence, log, and teardown operations are not network reconciliation steps. `synthran.app.workflows` defines state-sensitive policy for:

```text
run-baseline
run-congestion
stop
collect
logs-network
logs-open5gs
logs-ue
down
```

These actions still flow into the same `OperationController` after policy evaluation.

Key rules include:

- provider-facing workflow plans require current controller, project-access, and provider-experiment observations;
- experiment start requires a current `PATH_PROVEN` path;
- stop requires a current running experiment;
- collect/log workflows are non-mutating R1 plans;
- teardown is R3, refuses a running experiment, requires current non-foreign ownership, and binds exact resource IDs.

Authorization recomputes workflow policy and exact target scope so plan approval cannot survive relevant state drift.

## Operation control plane

One operation is represented by an immutable `OperationPlan` plus mutable status and append-only events.

Plans bind:

- experiment identity;
- operation kind and risk;
- desired-state digest;
- observed-state digest;
- reconciliation/workflow-policy digest;
- exact targets when applicable;
- bound input digests such as a `ResourceDecision`;
- the overall plan digest.

R2 operations require standard approval. R3 operations require destructive approval. Approval is bound to the exact plan.

Authorization rechecks current policy/inputs and, for mutation, acquires the workspace-wide exclusive mutation claim. Failed/interrupted mutations retain that claim unless clean rollback is proven.

`ExecutionPermit` is the handoff to a concrete executor. It does not override live provider checks.

See `docs/operation-control.md`.

## Structured operation events

Operation progress uses validated events rather than parsing provider output:

```text
operation.started
plan.created
approval.requested
approval.granted
operation.authorized
stage.started
stage.progress
stage.completed
stage.failed
state.changed
operation.completed
operation.failed
operation.interrupted
recovery.required
```

`TerminalSession.operation_updates()` obtains the validated stream through `ApplicationController.operation_events()`. Raw SSH/POS/Kubernetes/Ansible output is never interpreted by the terminal as trusted operation state.

The event plumbing is implemented. Provider/domain execution still has to be connected for a terminal plan to emit real live stage progress.

See `docs/operation-events.md`.

## Resource selection and transactions

Resource selection is deterministic and capability-based.

`select_resources()` consumes:

- reviewed `ResourceDescriptor` objects;
- fresh complete provider snapshots;
- desired-state-derived requirements.

It returns a `ResourceSelection`. `ResourceDecision` binds the selection and exact targets into an immutable operation input so placement drift invalidates authorization.

The generic transaction layer coordinates acquisitions through `ResourceProviderAdapter`:

```text
ExecutionPermit
+ ResourceDecision
+ provider adapters
-> execute_resource_transaction()
```

Provider acquisition receipts distinguish requested resources from resources actually created by the operation. Only exact `created_ids` are generic rollback authority. Rollback runs in reverse provider order. Adapter exceptions or incomplete rollback yield recovery-required state instead of guessed cleanup.

The generic transaction engine is implemented; concrete transaction adapters for every SLICES/R2Lab path are not yet connected to the terminal control plane. Provider-specific scripted executors elsewhere in the repository do not automatically satisfy this boundary.

See `docs/resource-selection.md`, `docs/resource-operation-binding.md`, and `docs/resource-transaction.md`.

## Why complete pinned checkouts are reused

`5g_ansible` behavior is distributed across inventory variables, playbooks, roles, templates, Helm integration, and shell entry points. Extracting only selected files would silently inherit dependencies on the rest of the tree and make SynthRAN responsible for reconstructing upstream behavior.

A complete detached checkout preserves those relationships. SynthRAN executes only the reviewed Open5GS + srsRAN + RFSIM path through a narrow adapter. Contiki-NG follows the same rule: the checkout remains complete and pinned while the SynthRAN sensor application stays out of tree under `deploy/iot/sensor/`.

This is composition, not a Git merge. `.deps/` is local and ignored. No upstream history or copied source tree is added to SynthRAN.

## Accepted golden-path data flow

The current accepted virtual path is:

1. Ten deterministic Cooja sensors join one RPL/6LoWPAN network.
2. A Cooja border router exposes its serial link through a deterministic loopback Serial Socket.
3. A strict loopback-only reverse SSH tunnel forwards the socket to the root core node.
4. Pinned Contiki-NG `tunslip6` creates run-scoped `tun0` on the core node.
5. Sensors publish run-scoped MQTT telemetry toward the border-router endpoint.
6. A counted TCP ingress forwards the MQTT byte stream toward a temporary Mosquitto sidecar in the run-owned srsUE pod.
7. The sidecar shares the srsUE network namespace containing `tun_srsue1` and binds to the dynamically discovered live PDU address.
8. A run-specific route sends central-broker traffic through `tun_srsue1`.
9. srsRAN/Open5GS carry the traffic to a run-owned central Mosquitto broker.
10. A central collector validates run-scoped telemetry and appends canonical JSONL.
11. PyArrow derives deterministic Parquet from accepted JSONL.
12. Route/interface/broker/message evidence plus accepted UPF proof and cleanup reproof establish acceptance.

The counted TCP ingress is an integration adapter, not the cellular proof boundary. The cellular bridge starts inside the srsUE namespace because that is where the UE tunnel and live PDU exist.

## Accepted network boundary

The current live-accepted network configuration is intentionally narrow: Open5GS + srsRAN + one srsUE + RFSIM + one slice.

The supported Linux controller verifies SLICES authentication/project/experiment context but does not log in, change projects, or create the provider experiment.

The explicit scripted preparation path can create/verify a reservation, jointly allocate the reviewed compute pair, image/reset nodes, build Kubernetes, and install pinned direct tooling. It stops before 5G deployment.

The explicit deployment path revalidates fresh preflight evidence, uses the locked `5g_ansible` checkout plus reviewed SynthRAN overlays, passes immutable transitive commits, pins selected runtime images, and ends at `deployed-unverified`.

A separate read-only network verifier proves the run-owned gNB, srsUE, selected UPF, gNB cell activation, `tun_srsue1`, current PDU/route, and UPF `ogstun` path. Only that proof marks the network `path-proven`.

## Experiment mutation boundary

The accepted IoT experiment makes narrow run-scoped changes on top of the accepted base network, including run-labeled MQTT configuration/deployment, a temporary sidecar/route, local Cooja, strict SSH forwarding, remote `tunslip6`, counted ingress, and run-owned broker/collector processes.

Cleanup is exact and fail-closed. It reaps run-owned process groups, removes run-created `tun0` and remote workspaces, removes run-labeled Kubernetes objects/sidecar configuration, verifies absence postconditions, lets srsUE recover, reconciles RFSIM when necessary, and reproves the accepted base network.

Experiment cleanup does not mean base-network teardown.

## Controlled research architecture

Controlled research wraps the deterministic experiment in a fixed measurement window with:

- continuous RTT probing bound to `tun_srsue1`;
- optional controlled UDP iperf3 load;
- synchronized Ingress, UE `tun_srsue1`, and UPF `ogstun` counter sampling;
- immutable experiment specification and measurement-window records;
- JSONL/Parquet instrumentation artifacts;
- a consolidated validity-aware research summary.

The accepted calibration records about 67.25 Mbps over `tun_srsue1`. The accepted baseline run has complete telemetry and successful RTT/network instrumentation.

The historical load50 pilot is invalid evidence for a loaded-condition scientific result because the load was not established and the underlying RFSIM/5G path collapsed. Loaded-condition campaign conclusions remain pending fresh valid runs.

Campaign generation and offline analysis are implemented/tested, including blocked-by-seed scheduling and paired differences against baseline with bootstrap confidence intervals.

## Data boundary

The telemetry contract accepts the ten deterministic sensor identities. Valid records are appended to canonical JSONL. Malformed messages never enter the accepted dataset. Parquet is a deterministic derivative of JSONL, not a second source of truth.

Sequence acceptance detects missing sensors, gaps, and duplicates. Research validity additionally requires its independent load/path/probe/instrumentation conditions.

## Privacy boundary

Protection is layered:

1. ignore rules keep dependency trees, generated experiments, and credential-bearing paths out of normal Git status;
2. a tracked pre-push hook scans outgoing commits;
3. repository protections may reject supported credential patterns;
4. CI scans tracked source and Git history;
5. public derivatives use deterministic redaction while raw sensitive artifacts remain local.

Checks fail closed and report rule/location without copying detected values into logs. The default acceptance path does not require packet capture; route proof, counters, broker receipt, and UPF evidence provide a lower-risk proof surface.
