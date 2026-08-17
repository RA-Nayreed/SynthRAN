# Interactive terminal shell

Running `synthran` with no arguments opens the session-first interactive terminal. Supplying any explicit arguments preserves the existing scripted CLI unchanged.

```text
synthran                     # interactive terminal
synthran doctor ...          # scripted CLI
synthran network verify ...  # scripted CLI
```

The executable is a thin launcher. `synthran/cli.py` remains the single registration and implementation source for the scripted command tree; the launcher only chooses interactive versus scripted mode from whether argv is empty.

## First launch

If no persistent `workspace.toml` exists, the terminal starts a verified initialization flow instead of exiting immediately.

The flow asks only for stable controller/workspace identity:

- controller profile name;
- SLICES project;
- SLICES username when creating a new profile;
- optional R2Lab slice and exact SSH identity when R2Lab is enabled.

An existing profile is reused without asking the operator to re-enter its identity fields. `SYNTHRAN_SLICES_PROJECT` is used only as a prompt default; the initialization service still verifies the selected live project read-only before local persistence.

Initialization never reserves, allocates, powers, deploys, or changes provider resources. It verifies access first and persists local workspace/profile/access state only after the read-only checks succeed.

When the initialized workspace has no active experiment, the terminal offers to create one through `ApplicationController.create_experiment()`. The default request is `iot-to-5g` with virtual RFSIM radio. A provider experiment can be bound from the prompt or left unset; live control remains fail-closed when no provider binding exists.

### Existing live-run artifacts

A checkout may already contain legacy experiment evidence such as:

```text
.synthran/preparations/
.synthran/runs/
.synthran/experiments/iot-acceptance-*/
.synthran/experiments/pilot-*/
```

These paths are compatible with first-launch adoption. Initialization creates the persistent workspace metadata alongside them and does not move, rename, rewrite, or delete the accepted legacy evidence.

New-format experiment folders use `sran-YYYYMMDD-NNN`, so the registry can coexist with legacy experiment run IDs and ignores unrelated directory names when rebuilding indexes.

Initialization fails closed when `.synthran` contains ambiguous partial new-workspace state without `workspace.toml`, including `registry.sqlite3`, `active.json`, persistent access records, `sran-*` experiment directories, or `op-*` operation directories. That state must be recovered rather than guessed.

Rollback is ownership-safe. When adopting an existing `.synthran`, a failed initialization removes only profile/workspace/access objects created by that attempt; pre-existing run, preparation, experiment, evidence, and dataset artifacts remain untouched.

## Prompt model

The shell uses `prompt_toolkit` for input, completion, history, and the bottom toolbar. It does not own provider state or lifecycle authority.

A session starts in OBSERVE mode:

```text
SynthRAN interactive terminal
Mode: OBSERVE  |  /help for commands
synthran[OBSERVE]>
```

The bottom toolbar is derived from the current `ApplicationSnapshot` and shows mode, lifecycle, and active SynthRAN experiment. It is a view only and performs no provider mutation.

Command completion is generated from the strict terminal registry. Fixed subcommands are completed from the same registry, so completion cannot introduce hidden commands or provider/resource overrides.

History is in-memory by default. Terminal commands therefore are not copied to a second durable history file. Durable application and operation evidence remains under the workspace state model.

## Dispatch boundary

`TerminalSession` handles local UI/read-only commands and returns workflow commands as structured `CommandRequest` objects. `TerminalCommandRouter` is the only interactive dispatch boundary.

Every registered workflow command now reaches the shared application layer and either returns a policy error or creates an immutable operation plan:

| Terminal command | Application action |
|---|---|
| `/reserve` | plan the current `reserve` reconciliation step |
| `/up` | plan exactly one current progression step: `reserve`, `allocate`, `prepare`, or `up` |
| `/verify` | plan the current read-only `verify-path` step |
| `/recover` | plan one explicit `recover-*` step when reconciliation exposes exactly one |
| `/run baseline` | plan R2 `run-baseline` only from current `PATH_PROVEN` state |
| `/run congestion` | plan R2 `run-congestion` only from current `PATH_PROVEN` state |
| `/stop` | plan R2 `stop` only while an experiment is currently running |
| `/collect` | plan R1 evidence collection from a current proven path |
| `/logs network` | plan R1 sanitized network-log access when network runtime state exists |
| `/logs open5gs` | plan R1 sanitized Open5GS-log access when a current core runtime exists |
| `/logs ue` | plan R1 sanitized UE-log access when a current UE runtime exists |
| `/down` | plan R3 teardown only after the experiment is stopped and current ownership facts permit teardown |
| `/config resources` | render durable workspace resource policy |
| `/config experiment` | render the active experiment projection |

Resource-bound network planning requires a fresh `ResourceInventory` supplied through an inventory adapter. If no fresh adapter is configured, the router fails closed before creating an operation.

`/up` never silently turns path verification into a mutation. When the network is ready and `verify-path` is next, it instructs the operator to use `/verify`.

The experiment/evidence/log/teardown commands are evaluated by a pure application workflow policy and then passed into the same `OperationController` used for reconciliation. Their operation plans are therefore bound to the exact desired state, observed-state digest, policy digest, risk class, approval mode, operation journal, and concurrency model rather than being terminal-only actions.

## Workflow policy

Application workflow planning is intentionally state-sensitive:

- experiment start requires current `PATH_PROVEN` evidence and refuses to start over an already running experiment;
- stop requires a current `EXPERIMENT_RUNNING` observation;
- collection is R1 and requires a current proven path;
- component log operations are R1 and require the relevant runtime to exist;
- teardown is R3, refuses to run while the experiment is active, and refuses stale, foreign, or unknown ownership facts before a destructive plan can be created.

A change to desired state, observed state, workflow policy, or bound inputs after plan review invalidates later authorization through the shared operation-engine drift checks.

## Provider execution boundary

Planning is not execution. A planned operation prints its operation ID, risk, approval requirement, and `Execution: not started`.

The terminal does **not** tunnel a workflow into the legacy CLI to make it appear implemented. That would bypass the shared application, immutable operation plan, approval, ownership, freshness, and provider-adapter boundaries.

The interactive router now has a first-class application plan for every registered workflow command, but provider/domain execution remains a separate boundary. A future executor must consume an authorized `ExecutionPermit`, perform its live provider checks immediately before any mutation, emit only structured progress events to the terminal, and preserve recovery-required semantics on partial failure.

Until the corresponding provider/domain adapters are connected, creating a plan does not reserve, deploy, start, stop, collect, read remote logs, or tear down provider resources. The existing explicit scripted CLI remains available for operator-run live workflows and is not invoked secretly by the interactive terminal.

## Transcript and progress

Router output is copied into the visible `TerminalSession` transcript only after it passes the terminal line-safety contract. Application operation events are then rendered through `TerminalSession.operation_updates()` from the validated structured event journal.

The shell does not parse raw SSH, POS, Kubernetes, Ansible, R2Lab, or provider stderr to determine progress.

## Exit and interruption

- `/quit` closes only the terminal session.
- EOF closes the terminal session.
- Ctrl-C cancels the current input line and keeps the session open.
- `/clear` clears the visible terminal display/transcript only; durable experiment and operation evidence is untouched.

Provider-operation cancellation remains an operation-executor concern and must preserve the existing recovery-required semantics once mutation authority has been acquired.
