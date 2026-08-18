# Session-first terminal controller

The terminal session layer turns strict slash commands into inline transcript output or structured application requests. It never invokes provider commands directly.

A terminal session starts in OBSERVE mode and keeps only lightweight in-memory UI state:

- current mode;
- whether the session is closed;
- visible transcript lines.

Durable experiment, operation, approval, observed-state, and provider authority remain outside the terminal session.

## Local commands

The session resolves commands that can be answered safely from application or UI state:

```text
/status
/inspect resources|network
/mode observe|operate
/help
/clear
/quit
```

`/status` and `/inspect` call the shared application snapshot and render the result inline. They do not maintain a second persistent dashboard model.

`/help` is generated from the command registry. `/mode` changes only the terminal mutation policy. `/clear` removes the visible in-memory transcript without deleting operation evidence. `/quit` closes the current terminal session without changing provider resources.

## Routed commands

Commands that require an application workflow are returned as a structured `CommandRequest` with response action `dispatch`:

```text
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
```

`TerminalCommandRouter` is the single interactive dispatch boundary. It maps commands only through application-layer state and policy; it does not call the scripted CLI as a hidden executor.

Current routing covers every registered workflow command:

- `/reserve` plans the exact current `reserve` reconciliation step and requires fresh provider inventory because it is resource-bound;
- `/up` plans exactly one current progression step among `reserve`, `allocate`, `prepare`, or `up`; it never turns `verify-path` into a mutation;
- `/verify` plans the current R1 `verify-path` operation;
- `/recover` plans one explicit `recover-*` reconciliation step when exactly one is exposed;
- `/run baseline|congestion` uses application workflow policy and requires current control authority plus `PATH_PROVEN` state;
- `/stop` requires a currently running experiment;
- `/collect` and `/logs ...` produce R1 read-only workflow plans subject to current-state prerequisites;
- `/down` produces an R3 destructive plan only after the experiment is stopped and exact current teardown targets are known;
- `/config resources|experiment` renders durable workspace/application configuration without mutation.

In OBSERVE mode, mutating requests are rejected before they can become dispatch requests.

## Planning versus execution

A successful routed workflow currently creates an immutable `OperationPlan` and renders its ID, kind, risk, approval requirement, and:

```text
Execution: not started
```

That is intentional. The terminal has first-class application policy for every registered workflow command, but the corresponding provider/domain executor boundary is not yet connected for terminal workflows.

A terminal plan therefore does not itself reserve, allocate, deploy, verify the live network, start or stop a research run, collect remote artifacts, read remote logs, or tear down provider resources.

The current explicit scripted CLI remains the operator path for live provider execution. The terminal must not invoke that CLI secretly because doing so would bypass the shared immutable plan, approval, drift, ownership, and provider-adapter architecture.

## Inline transcript

The session transcript contains only validated single-line entries classified as:

```text
command
result
system
error
```

Valid command entries are normalized from the strict parser, so arbitrary provider/resource overrides do not enter the transcript through the command line.

Router results are copied into the transcript through `record_dispatch_result()` only after passing the same terminal line-safety contract.

`/clear` clears only these visible lines. Durable `.synthran/operations/*` and `.synthran/sessions/events.jsonl` records are unaffected.

## Status rendering

The status renderer uses `ApplicationSnapshot` and prints truthful values for:

- lifecycle;
- workspace, profile, and project;
- active SynthRAN experiment;
- provider experiment binding;
- intent and radio mode;
- current block reasons or next reconciliation actions.

Missing values render as `—` rather than fabricated defaults.

`/inspect resources` renders only controller/project/provider-experiment/reservation/allocation/preparation/R2Lab-lease dimensions.

`/inspect network` renders Kubernetes/core/RAN/UE/PDU/UPF/radio/IoT/path/experiment/dataset dimensions.

Every dimension line includes freshness, source, and ownership from the reconciled snapshot.

## Operation updates

`TerminalSession.operation_updates()` reads the validated operation event stream through `ApplicationController.operation_events()` and renders only events after a supplied sequence cursor.

This supports terminal output such as:

```text
[path-check] running
[path-check] 2/3
[path-check] ready
Operation op-000041: completed
```

The session never parses raw provider stdout/stderr to create these lines. It renders only the structured event vocabulary validated by the operation layer.

## Interactive shell

The production shell is implemented with `prompt_toolkit` and calls `TerminalSession.submit()` plus `TerminalCommandRouter.dispatch()`. It provides registry-backed completion, in-memory history, OBSERVE/OPERATE prompts, and a bottom toolbar derived from `ApplicationSnapshot`.

Running `synthran` with no arguments opens this shell. Supplying any explicit arguments delegates to the existing scripted CLI. On first launch in an uninitialized checkout, the shell runs the verified local workspace initialization flow; there is currently no separate top-level scripted `synthran init` command.

See `docs/terminal-shell.md` for first-launch adoption, experiment setup, and the provider-execution boundary.
