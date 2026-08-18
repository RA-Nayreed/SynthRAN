# SynthRAN Repository Instructions

## Purpose

SynthRAN is a reproducible experiment-control platform joining deterministic IoT emulation, programmable 5G/Open RAN infrastructure, and research-grade datasets.

The accepted virtual golden path is:

```text
10 deterministic Contiki-NG/Cooja sensors
-> RPL/6LoWPAN border router
-> Cooja Serial Socket
-> loopback-only reverse SSH tunnel
-> remote tunslip6/tun0
-> counted TCP ingress
-> Mosquitto bridge inside the srsUE network namespace
-> tun_srsue1
-> srsRAN gNB
-> Open5GS UPF
-> run-owned central Mosquitto
-> canonical JSONL
-> deterministic Parquet
```

SynthRAN owns orchestration, contracts, integration adapters, validation, evidence, cleanup, and reproducibility reporting. It does not reimplement Open5GS, srsRAN, Contiki-NG, Cooja, Mosquitto, or iperf3.

## Integration truth

`main` is the integration truth. Before substantial work, inspect current `main`, current docs, and current tests rather than relying on an older PR description or planning note.

Development history is not product architecture. Do not encode temporary PR labels or internal planning terminology into public commands, schemas, generated filenames, or runtime statuses.

There is one product executable: `synthran`.

- `synthran` with no arguments opens the `prompt_toolkit` interactive terminal.
- `synthran <explicit arguments>` delegates to the existing scriptable CLI.

The two interfaces are not yet identical execution paths. The interactive terminal uses the persistent workspace, `ApplicationController`, workflow/reconciliation policy, and operation engine. The legacy scripted CLI still calls established network, experiment, research, and R2Lab executors directly. Do not hide that difference.

New shared lifecycle/domain functionality should be placed below the interface boundary so both interfaces can converge on the same application/domain services. The terminal must never invoke the scripted CLI secretly to make a command appear implemented.

## Interactive terminal contract

The terminal command registry is authoritative. Current commands are:

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

Do not document or implement hidden lifecycle commands outside this registry.

A session starts in OBSERVE mode. Mutating commands are rejected before dispatch until the operator selects OPERATE mode. OPERATE mode is not operation approval; normal immutable-plan, approval, freshness, ownership, and concurrency gates still apply.

Current interactive behavior is **planning-first**:

```text
slash command
-> TerminalSession
-> TerminalCommandRouter
-> ApplicationController
-> network reconciliation or application workflow policy
-> immutable OperationPlan
-> approval / authorization boundary
-> ExecutionPermit
-> provider/domain executor
```

The last provider/domain executor boundary is not yet connected for terminal workflows. `/reserve`, `/up`, `/verify`, `/recover`, `/run`, `/stop`, `/collect`, `/logs`, and `/down` can create valid state-sensitive operation plans or fail closed, but a plan currently reports `Execution: not started`. Do not claim that the terminal itself performed the provider action.

The current explicit scripted CLI remains the operator path for live provider execution.

## Application and state invariants

`ApplicationController` is the interactive application boundary. Terminal code may render application state and submit structured requests, but must not become a second owner of provider state or lifecycle rules.

Keep requested and discovered state separate:

- `ExperimentDesiredState` contains declared intent and implementation constraints.
- `ObservedState` contains discovered provider/runtime facts.
- Dynamic PDU addresses, allocated node identifiers, pod names, reservation identifiers, and other discovered values do not belong in desired state.

The observed-state truth ranking is exactly:

```text
provider
> observation
> evidence
> manifest
> cache
```

Fresh provider/direct observations are the only live tiers. Persisted evidence and manifests remain valuable provenance but do not become current mutation authority merely because they once succeeded.

Stale observations cannot authorize mutation. Unknown, foreign, expired, or ambiguous ownership fails closed.

Current observed dimensions are defined by `synthran.workspace.observed.OBSERVED_DIMENSIONS`; do not duplicate a divergent list in interface code.

## Reconciliation invariant

`plan_reconciliation()` is pure and emits only the next safe boundary. It does not execute provider commands.

The normal progression is state-dependent and includes inspection boundaries. A representative progression is:

```text
inspect controller/project/provider experiment
-> inspect reservation
-> reserve when absent
-> inspect allocation
-> allocate when absent
-> verify R2Lab lease when physical radio is requested
-> inspect preparation
-> prepare when absent
-> inspect network runtime
-> up when required network components are absent
-> verify-path when the network is ready but the path is not currently proven
```

Do not invent a separate `deploy` reconciliation step or skip required inspections.

Lifecycle values are derived from current desired/observed state and currently include:

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

## Application workflow policy

Experiment/evidence/log/teardown actions are not forced into network reconciliation. `synthran.app.workflows` defines separate policy for:

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

These actions still use the same `OperationController` after policy evaluation.

Important current gates:

- provider-facing workflows require current controller, project-access, and provider-experiment observations;
- experiment start requires current `PATH_PROVEN` state;
- stop requires a current running experiment;
- collection and log workflows are read-only operation plans;
- teardown is R3, refuses a running experiment, requires current non-foreign ownership, and binds exact resource IDs before a destructive plan is created.

Policy and target scope are recomputed at authorization so post-approval drift fails closed.

## Operation control plane

The operation layer owns immutable plans, approval records, event journals, exclusive mutation claims, interruption, and recovery-required state.

Risk classes are:

```text
R0  local/read-only inspection
R1  live/read-only verification or evidence access
R2  controlled mutation requiring standard approval
R3  destructive mutation requiring destructive approval
```

Use the registry/policy definitions for a command's exact risk rather than maintaining another hand-written command-to-risk table.

An `OperationPlan` is bound to the desired-state digest, observed-state digest, policy/reconciliation digest, exact targets, and any bound input digests. Approval is plan-specific. Authorization rechecks policy and state before issuing an `ExecutionPermit`.

Only one mutating operation may hold the workspace mutation claim. If an authorized mutation fails or is interrupted and clean rollback cannot be proven, preserve the claim and enter recovery-required state. Never release a mutation claim merely because a command returned an error.

`ExecutionPermit` is a handoff to an executor, not proof that live provider state remains safe. Concrete executors must perform their own final live checks immediately before mutation.

## Structured event invariant

Operation progress is represented by validated `OperationEvent` records, not by parsing terminal text or raw provider stdout/stderr.

Current event vocabulary includes operation lifecycle events plus:

```text
stage.started
stage.progress
stage.completed
stage.failed
state.changed
```

Provider/domain executors may retain detailed private logs in their existing evidence locations, but terminal progress must be mapped into the structured event model with bounded safe attributes.

## Workspace and identity

Persistent workspace identity is intentionally distinct from short-lived provider state.

- global profiles live under `~/.config/synthran/profiles/<name>.toml`;
- project workspace metadata lives under `.synthran/workspace.toml`;
- the SQLite registry allocates non-reusable experiment, run, and operation IDs;
- filesystem experiment/run/operation records remain durable provenance and allow registry reconstruction without identifier reuse.

Existing accepted legacy `.synthran` research artifacts may coexist with the newer persistent workspace. First-launch adoption must never move, rename, rewrite, or recursively delete those artifacts.

Initialization is performed by the no-argument interactive terminal when the checkout has no persistent workspace. There is currently no top-level scripted `synthran init` command. Do not document one unless it is actually added to the parser and tested.

Provider experiment creation remains an operator action. SynthRAN may persist a binding to an existing provider experiment but does not perform SLICES login, project changes, or provider experiment creation.

## Resource selection and transactions

Use the actual resource APIs and names in `synthran.resources`.

- `select_resources()` performs deterministic capability-based placement over reviewed descriptors and fresh complete provider inventory.
- `ResourceDecision` binds a selection and exact targets to an operation.
- `execute_resource_transaction()` coordinates provider acquisitions through `ResourceProviderAdapter` implementations.
- `AcquisitionReceipt.created_ids` is the only generic rollback authority for newly created resources.
- rollback proceeds in reverse provider order and releases only exact created IDs.
- adapter exceptions or incomplete rollback produce recovery-required state rather than guessed cleanup.

The generic transaction layer is implemented, but concrete transaction adapters for all provider paths are not yet connected. In particular, do not claim that the generic terminal operation path can already reserve/allocate SLICES or control R2Lab merely because provider-specific legacy executors exist elsewhere.

## Live acceptance truth

The supported virtual configuration is deliberately narrow:

- core: Open5GS;
- RAN: srsRAN;
- radio: RFSIM;
- UE: one srsUE used as the IoT edge gateway;
- one SST-1 slice with DNN `internet`;
- exactly ten deterministic Contiki-NG/Cooja sensors;
- JSONL as append-only audit data and deterministic Parquet as its derivative;
- controlled research load protocol: UDP.

Accepted evidence currently proves:

- base network `network-acceptance-20260817-04`: `PATH PROVEN`;
- IoT-to-5G `iot-acceptance-20260817-06`: `IOT-TO-5G PATH PROVEN`;
- capacity calibration `calibration-20260817-02.json`: 67,253,028 bps;
- baseline research run `pilot-20260817-03-baseline`: ready for campaign analysis with complete telemetry and RTT evidence.

`pilot-20260817-03-load50` is invalid loaded-condition evidence. The load did not establish successfully and the underlying RFSIM/5G path collapsed. Do not cite it as proof of congestion behavior. Fresh valid loaded runs are still required before scientific conclusions about load50/load80/load95.

Physical radio acceptance, multiple UEs/slices, TCP research load, impairment campaigns, formal A1/E2, RIC integration, generative models, synthetic telemetry, and automated RAN-policy synthesis remain deferred unless current accepted evidence and a recorded decision change that status.

## Dependency boundary

Reuse `sopnode/5g_ansible` and Contiki-NG as complete pinned external checkouts. Keep dependency trees under ignored `.deps/` storage. Do not vendor them, merge their branches into SynthRAN, or copy selective source files merely for convenience.

Keep selected runtime images digest-pinned. Preserve third-party license/provenance records. Dependency updates require lock updates and focused regression tests.

`environment.yml` is the complete supported Linux Conda environment. `dependencies.lock.yml` is authoritative for direct locked inputs. Do not add a direct dependency to only one file and leave the other source of dependency truth stale.

## Live safety boundary

The live operator controls external infrastructure changes.

An agent may:

- author code, tests, docs, schemas, and configuration;
- inspect repository/dependency/provider state read-only;
- run safe offline validation;
- prepare non-mutating plans;
- analyze operator-provided evidence.

An agent must not reserve resources, deploy infrastructure, power physical equipment, run live experiments, or perform broad/destructive provider cleanup without explicit user authorization for that live action.

Never guess resource ownership. Never use broad cleanup such as `pkill`, `killall`, wildcard resource deletion, or guessed provider IDs where exact run ownership is required.

## Credentials and privacy

Never commit subscriber credentials, SLICES tokens, kubeconfigs, private keys, secret-bearing environment files, private authority files, unsanitized packet captures/logs, dependency worktrees, or generated run directories.

Privacy controls are layered through ignore rules, the tracked pre-push hook, repository scanning, GitHub protections, and Gitleaks. Never weaken a privacy rule merely to make a scan pass without a narrow documented reason and regression coverage.

The default acceptance path prefers route proof, counters, broker receipt, and message-integrity evidence over packet capture.

## Decision journal

`decision.md` is local and intentionally untracked through `.git/info/exclude`, not tracked `.gitignore`.

Record material architecture, dependency, interface, security, workflow, safety, and scope decisions there using the established decision format. Promote durable implementation rules into `AGENTS.md`. Never put credentials or raw private provider data in the journal.

Do not claim that an untracked journal entry is independently verifiable from Git history.

## Validation before completion

From the repository root with the `synthran` Conda environment active, run the applicable checks, including:

```sh
python -m unittest discover -s tests -v
python -m synthran privacy scan --worktree
git diff --check
git status --short
```

When Git-history secret scanning is available locally or in CI, run it as well.

Before merging, inspect the complete intended diff and confirm that:

- docs describe current code rather than desired future behavior;
- no terminal command is documented outside the registry;
- planning is not described as provider execution;
- live-accepted and offline-tested claims are kept distinct;
- invalid experiment evidence remains labeled invalid;
- desired/observed boundaries and ownership rules are preserved;
- dependency and privacy invariants remain intact.
