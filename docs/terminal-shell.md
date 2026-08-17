# Interactive terminal shell

Running `synthran` with no arguments opens the session-first interactive terminal. Supplying explicit arguments preserves the existing scripted CLI path.

```text
synthran                     # interactive terminal
synthran doctor ...          # scripted CLI
synthran network verify ...  # scripted CLI
```

The executable is a thin launcher. `synthran/cli.py` remains the registration/implementation source for the scripted command tree; the launcher only chooses interactive versus scripted mode from whether argv is empty.

## First launch

If no persistent `workspace.toml` exists, the terminal starts a verified initialization flow.

The flow asks for stable controller/workspace identity:

- controller profile name;
- SLICES project;
- SLICES username when creating a new profile;
- optional R2Lab slice and exact SSH identity when R2Lab is enabled.

An existing profile is reused without re-entering its identity fields. `SYNTHRAN_SLICES_PROJECT` is only a prompt default; the initialization service verifies the selected live project read-only before local persistence.

Initialization never reserves, allocates, powers, deploys, creates a provider experiment, or starts an experiment. It persists local workspace/profile/access state only after required read-only checks succeed.

When the initialized workspace has no active local experiment, the terminal offers to create one through `ApplicationController.create_experiment()`. The default request is `iot-to-5g` with virtual RFSIM radio. An existing provider experiment can be bound from the prompt or left unset; live-control planning remains fail-closed when no provider binding exists.

There is currently no top-level scripted `synthran init` command.

### Existing live-run artifacts

A checkout may already contain legacy experiment evidence such as:

```text
.synthran/preparations/
.synthran/runs/
.synthran/experiments/iot-acceptance-*/
.synthran/experiments/pilot-*/
```

These paths are compatible with first-launch adoption. Initialization creates persistent workspace metadata alongside them and does not move, rename, rewrite, or delete accepted legacy evidence.

New-format experiment folders use `sran-YYYYMMDD-NNN`, so the registry can coexist with historical run IDs and ignores unrelated directory names when rebuilding indexes.

Initialization fails closed when `.synthran` contains ambiguous partial new-format workspace state without `workspace.toml`, including registry/active/access records, `sran-*` experiment directories, or `op-*` operation directories.

Rollback is ownership-safe. When adopting an existing `.synthran`, a failed initialization removes only local profile/workspace/access objects created by that attempt; pre-existing run/preparation/experiment evidence remains untouched.

## Prompt model

The shell uses `prompt_toolkit` for input, completion, history, and the bottom toolbar. It does not own provider state or lifecycle authority.

A session starts in OBSERVE mode:

```text
SynthRAN interactive terminal
Mode: OBSERVE  |  /help for commands
synthran[OBSERVE]>
```

The bottom toolbar is derived from `ApplicationSnapshot` and shows mode, lifecycle, and active local experiment. It is a view only and performs no provider mutation.

Command completion is generated from the strict command registry. Fixed subcommands are completed from the same registry, so completion cannot introduce hidden commands or provider/resource overrides.

History is in-memory by default. Durable application/operation evidence remains under the workspace state model.

## Dispatch boundary

`TerminalSession` handles local UI/read-only commands and returns workflow commands as structured `CommandRequest` objects. `TerminalCommandRouter` is the only interactive dispatch boundary.

Current application routing is:

| Terminal command | Application action |
|---|---|
| `/reserve` | request planning of the current `reserve` reconciliation step |
| `/up` | request exactly one current progression step: `reserve`, `allocate`, `prepare`, or `up` |
| `/verify` | plan the current R1 `verify-path` step |
| `/recover` | plan one explicit `recover-*` step when reconciliation exposes exactly one |
| `/run baseline` | plan R2 `run-baseline` only from current `PATH_PROVEN` state |
| `/run congestion` | plan R2 `run-congestion` only from current `PATH_PROVEN` state |
| `/stop` | plan R2 `stop` only while an experiment is currently running |
| `/collect` | plan R1 evidence collection from a current proven path |
| `/logs network` | plan R1 network-log access when required current runtime state exists |
| `/logs open5gs` | plan R1 Open5GS-log access when a current core runtime exists |
| `/logs ue` | plan R1 UE-log access when a current UE runtime exists |
| `/down` | plan R3 teardown only after the experiment is stopped and current exact ownership/target rules pass |
| `/config resources` | render durable workspace resource policy |
| `/config experiment` | render the active experiment projection |

`/up` never silently turns path verification into mutation. When the network is ready and `verify-path` is next, it instructs the operator to use `/verify`.

Experiment/evidence/log/teardown actions are evaluated by application workflow policy and passed into the same `OperationController` used for reconciliation. Their plans are bound to current desired state, observed-state digest, policy/reconciliation digest, risk, target scope, and bound inputs where applicable.

## Current resource-inventory limitation

Resource-bound network planning (`reserve`, `allocate`, `prepare`, and `up`) requires a fresh complete `ResourceInventory` supplied through `TerminalCommandRouter.inventory_source`.

The production shell currently constructs the router without a live inventory source:

```text
TerminalCommandRouter(app)
```

Therefore a stock interactive `/reserve`, or `/up` when its next step is resource-bound, currently fails closed before creating an operation plan with an error stating that fresh provider inventory is required.

This is distinct from the existing scripted live resource/preparation commands. The terminal must not invoke those commands secretly to manufacture inventory or bypass the application/resource-decision boundary.

A future production inventory adapter must obtain fresh complete provider state and feed the existing `ResourceInventory`/`ResourceDecision` path.

## Workflow policy

Application workflow planning is intentionally state-sensitive:

- experiment start requires current controller/project/provider-experiment authority plus `PATH_PROVEN` state;
- stop requires a current running experiment;
- collection is R1 and requires a current proven path;
- component log operations are R1 and require the relevant current runtime;
- teardown is R3, refuses an active experiment, and requires fresh non-foreign ownership plus exact resource IDs before a destructive plan can be created.

A change to desired state, observed state, workflow policy, targets, or bound inputs after plan review invalidates later authorization through shared drift checks.

## Provider execution boundary

Planning is not execution. A planned operation prints its operation ID, risk, approval requirement, and:

```text
Execution: not started
```

The terminal does **not** tunnel a workflow into the legacy CLI to make it appear implemented. That would bypass the persistent application, immutable operation plan, approval, ownership, freshness, target, and provider-adapter boundaries.

The interactive router has application policy for all registered workflow commands, but provider/domain execution remains separate. A concrete executor must consume an authorized `ExecutionPermit`, perform final live/domain checks, emit structured progress events, and preserve recovery-required semantics on partial/unknown failure.

Until those executor bindings are connected, creating a terminal plan does not execute a reservation, deployment, verification, experiment start/stop, remote collection/log read, or teardown. The existing explicit scripted CLI remains the live operator path and is not invoked secretly by the terminal.

## Transcript and progress

Router output is copied into the visible transcript only after it passes terminal line-safety validation. Application operation events are rendered through `TerminalSession.operation_updates()` from the validated structured event journal.

The shell does not parse raw SSH, POS, Kubernetes, Ansible, R2Lab, experiment, or research stderr/stdout to determine trusted progress.

The structured event plumbing is implemented, but real stage progress requires a concrete executor to authorize and run the operation. Initial plan events do not mean provider execution started.

## Exit and interruption

- `/quit` closes only the terminal session.
- EOF closes the terminal session.
- Ctrl-C cancels the current input line and keeps the session open.
- `/clear` clears visible terminal display/transcript state only; durable experiment and operation evidence is untouched.

Provider-operation cancellation remains an executor concern and must preserve recovery-required semantics once mutation authority has been acquired.
