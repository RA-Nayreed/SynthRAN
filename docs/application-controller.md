# Shared application controller

`ApplicationController` is the persistent application boundary used by the interactive terminal. It coordinates workspace authority, desired/observed state, reconciliation, application workflow policy, resource decisions, and the operation controller without duplicating those rules in UI code.

The architectural goal is a shared application/domain layer for interactive and scripted interfaces, but the repository has **not completed that convergence yet**. The existing scripted CLI still invokes established network, experiment, research, and provider-specific executors directly for many live workflows. The terminal must not call that CLI secretly to bypass the application/operation boundary.

Current interactive control flow is:

```text
terminal command
      |
      v
TerminalCommandRouter
      |
      v
ApplicationController
  |-- workspace authority
  |-- experiment desired state
  |-- observed-state cache
  |-- network reconciliation policy
  |-- experiment/evidence/log/teardown workflow policy
  |-- resource decision binding
  `-- operation controller
      |
      v
ExecutionPermit
      |
      v
provider/domain executor boundary
```

The final provider/domain executor boundary is not yet connected for terminal workflows.

## Local status

`snapshot()` is safe to call without changing provider resources. It reports:

- workspace root, profile, and SLICES project;
- active SynthRAN experiment ID;
- bound provider experiment when present;
- experiment intent and radio mode;
- derived lifecycle;
- observed dimensions with state, source, ownership, and freshness;
- current reconciliation steps and block reasons.

If the workspace has no active experiment, lifecycle is `EMPTY`. If an active experiment has no observed-state file yet, the controller creates only an in-memory empty observation set for status calculation. It does not persist invented provider facts.

A stale observation remains visible but is marked `fresh = false`. Reconciliation therefore requests inspection instead of treating old state as mutation authority.

## Experiment creation

The application controller creates detailed local SynthRAN experiments from initialized workspace profile/project state. A user interface supplies experiment-specific requested state, label, and optional provider-experiment binding; it does not ask again for stable controller identity.

Detailed requested state is persisted by the workspace experiment service and experiment IDs remain non-reusable.

Creating a SynthRAN experiment record does not create the provider experiment. Provider experiment creation remains an external operator action.

## Observation ingestion

Provider/domain adapters submit source-specific `Observation` objects to `record_observations()`. The controller applies the shared truth order and persists only the reconciled observed-state snapshot.

The application layer does not reinterpret raw provider text. Parsing and ownership proof belong to adapters. This keeps provider-specific assumptions out of terminal UI code.

## Network reconciliation operations

`begin_operation()` loads active desired and observed state and delegates one current network reconciliation step to the approval-gated operation controller. Resource-bound steps additionally bind the exact current `ResourceDecision` digest and targets.

Live control planning requires a durable provider-experiment binding. This prevents a terminal field from silently targeting an untracked provider experiment.

Resource-bound operations also require fresh complete inventory. Placement is therefore derived from durable requested state plus current provider inventory, not inline terminal overrides.

## Application workflow operations

Not every action is a network reconciliation step. Once the base network state permits it, experiment/evidence/log/teardown commands use state-sensitive application policy while still using the same operation engine.

`begin_workflow_operation()` evaluates policy for:

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

The resulting policy report is handed into `OperationController`; it is not executed by a second controller. Operation IDs, immutable plan hashing, desired/observed binding, risk, approvals, event journaling, mutation claims, interruption, and recovery semantics therefore remain shared within the interactive control plane.

The operation engine accepts either normal network reconciliation or an explicit application workflow report. Authorization recomputes the corresponding policy so policy drift is rejected in the same way as reconciliation drift.

For `down`, the application additionally binds exact current resource IDs into the immutable target list and recomputes that target list at authorization.

## Approval and authorization handoff

`approve_operation()`, `authorize_operation()`, `finish_operation()`, and `interrupt_operation()` are application-level handoffs to the operation engine.

Authorization rechecks current desired/observed state plus reconciliation/workflow policy and any bound resource decision. Mutating authorization acquires the exclusive workspace mutation claim.

A returned `ExecutionPermit` means the local application control gates agreed at that instant. It does not mean a provider mutation occurred and it does not permit an executor to skip final live checks.

## Resource transaction integration

`execute_resource_operation()` is the implemented high-level application path for a resource operation that already has:

- an approved resource-bound operation plan;
- fresh current `ResourceInventory`;
- a matching `ResourceDecision`;
- concrete provider adapters for every real provider in the decision.

It validates adapters before authorization, authorizes the operation, executes the generic transaction, and maps transaction outcome into normal operation completion/recovery semantics.

The generic transaction engine exists, but concrete transaction adapters for every SLICES/R2Lab workflow are not yet connected to the terminal. Existing provider-specific scripted executors elsewhere in the repository are not silently substituted.

## Terminal execution boundary

Every registered terminal workflow now reaches this application layer and either fails policy or creates an immutable operation plan. That includes `/run`, `/stop`, `/collect`, `/logs`, and `/down`.

The terminal currently stops after planning and renders:

```text
Execution: not started
```

Provider/domain execution for those terminal plans remains separate work. A future concrete executor must consume an authorized permit, perform its own live checks, emit structured operation events, and preserve recovery-required semantics.

Until that is connected, the existing explicit scripted CLI remains the operator path for live network, experiment, research, and provider-specific execution.

## Interface rule

Terminal code may call this application layer or a provider/domain adapter reached through an approved application executor. It must not directly invoke `pos`, `slices`, `ssh`, `kubectl`, `ansible-playbook`, R2Lab mutation commands, or the legacy CLI as a hidden shortcut.

Likewise, new shared domain behavior should not be duplicated separately in terminal and CLI implementations. Put shared state/policy/executor logic beneath the interfaces and migrate explicit callers deliberately.
