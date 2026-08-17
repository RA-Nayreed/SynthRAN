# Shared application controller

SynthRAN has one application service for both the terminal interface and scripted commands. The interface layer is responsible for input and rendering; it does not own a second copy of workspace, experiment, reconciliation, approval, or operation logic.

`ApplicationController` resolves the initialized workspace authority once and then coordinates the existing durable services:

```text
terminal / scripted command
          |
          v
ApplicationController
  |-- workspace authority
  |-- experiment desired state
  |-- observed-state cache
  |-- network reconciliation policy
  |-- experiment/evidence/log/teardown workflow policy
  |-- operation controller
          |
          v
provider executor boundary
```

## Local status

`snapshot()` is intentionally safe to call without changing provider resources. It reports:

- workspace root, profile, and SLICES project;
- active SynthRAN experiment ID;
- bound provider experiment when present;
- experiment intent and radio mode;
- derived lifecycle;
- observed dimensions with state, source, ownership, and freshness;
- current reconciliation steps and block reasons.

If the workspace has no active experiment, lifecycle is `EMPTY`. If an active experiment has no observed-state file yet, the controller creates only an in-memory empty observation set for the status calculation. It does not persist invented provider facts.

A stale observation remains visible but is marked `fresh = false`. Reconciliation therefore requests inspection instead of treating old state as mutation authority.

## Experiment creation

The application controller creates detailed experiments from the initialized workspace profile and project. A user interface supplies experiment-specific requested state, label, and optional provider experiment binding; it does not ask again for stable controller identity.

Detailed requested state is still persisted by the workspace experiment service and experiment IDs remain non-reusable.

## Observation ingestion

Provider adapters submit source-specific `Observation` objects to `record_observations()`. The controller applies the shared truth order and persists only the reconciled observed-state snapshot.

The application layer does not reinterpret raw provider text. Parsing and ownership proof belong to provider adapters. This keeps provider-specific assumptions out of the terminal UI.

## Network reconciliation operations

`begin_operation()` loads the active desired and observed state and delegates one current network reconciliation step to the approval-gated operation controller. Resource-bound steps additionally bind the exact current `ResourceDecision` digest and targets.

Live control requires a durable provider experiment binding. This prevents a command-line or terminal field from silently targeting an untracked provider experiment.

## Application workflow operations

Not every application action is a network reconciliation step. Once the network is path-proven, experiment and research commands require their own state-sensitive policy while still using the same operation engine.

`begin_workflow_operation()` evaluates the pure application workflow policy for:

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

The resulting policy report is handed into the existing `OperationController`; it is not executed by a second controller. Operation IDs, immutable plan hashing, desired/observed-state binding, risk classes, approvals, event journaling, mutation claims, interruption, and recovery semantics therefore remain shared.

The operation engine accepts either the normal network reconciliation report or an explicit application policy report. Authorization must be given the corresponding freshly recomputed policy report, so policy drift is rejected in the same way as reconciliation drift.

The current terminal integration creates these plans only. Provider/domain adapters must be connected separately before the interactive terminal can authorize and execute them.

## Approval and execution handoff

`approve_operation()`, `authorize_operation()`, `finish_operation()`, and `interrupt_operation()` are thin application-level handoffs to the shared operation engine. Authorization still rechecks policy/reconciliation and freshness, and provider executors still perform their own live gates immediately before mutation.

Resource transactions already use `ExecutionPermit` plus exact provider adapters. Experiment, collection, log, and teardown executors must follow the same pattern rather than calling legacy CLI entry points behind the terminal.

## Interface rule

Terminal commands such as `/status`, `/inspect`, `/up`, `/verify`, `/run`, `/collect`, `/logs`, or `/down` call this application layer or a provider adapter reached through it. The terminal must not directly invoke `pos`, `slices`, `ssh`, `kubectl`, `ansible-playbook`, R2Lab resource commands, or the legacy scripted CLI as a hidden executor.

That boundary keeps interactive and scripted operation behavior consistent and makes safety policy testable without terminal rendering code.
