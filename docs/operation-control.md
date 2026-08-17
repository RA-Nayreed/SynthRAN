# Operation control boundary

SynthRAN separates policy from execution. Network reconciliation determines the next safe network action from desired state and current observed state. Application workflow policy separately governs experiment start/stop, evidence access, component logs, and teardown. The operation controller turns exactly one permitted action into a durable, reviewable operation and only then can issue an ephemeral execution permit.

The operation controller does not replace provider-specific safety checks. SLICES, POS, SSH, Kubernetes, Ansible, R2Lab, experiment, and research executors must still verify their own live authority and prerequisites immediately before provider interaction.

## Operation lifecycle

One operation uses a workspace-wide non-reusable ID such as `op-000041`. The workspace registry allocates the ID before extra operation records are written, so an interrupted creation attempt still consumes its identifier.

An operation directory contains:

```text
.synthran/operations/op-000041/
├── operation.json
├── plan.json
├── state.json
├── approval.json       # only for approved R2/R3 work
└── events.jsonl
```

The workspace also contains:

```text
.synthran/
├── operations/active-mutation.json   # only while a mutation is active or recovery is required
└── sessions/events.jsonl             # append-only cross-operation event stream
```

`operation.json` is the durable identity record allocated by the registry. `plan.json` is immutable. `state.json` is the current local operation status. `approval.json` is immutable approval evidence. Event logs contain sanitized control events, not copied provider command output.

## Immutable plan binding

An operation plan contains one selected action together with SHA-256 digests of:

- the detailed desired experiment state;
- the reconciled observed-state snapshot;
- the network reconciliation report or application workflow policy report;
- any explicitly bound inputs such as a `ResourceDecision`.

The plan also carries exact target IDs when the action requires a fixed target scope. The plan itself has a SHA-256 digest over all immutable plan fields. Loading a plan recomputes that digest and rejects modified content.

This prevents approval for one state/policy/target set from being silently reused after requested state, observed state, placement, workflow policy, or destructive target scope changes.

## Approval policy

Operation risk categories are:

| Risk | Meaning | Approval |
|---|---|---|
| R0 | local/read-only inspection | none |
| R1 | live/read-only verification or evidence access | none |
| R2 | controlled mutation | explicit standard approval |
| R3 | destructive mutation | explicit destructive approval |

Approval records are bound to the exact operation ID, plan digest, and risk class. R3 cannot use a standard R2 approval.

Approval is a local operator-consent record, not a replacement for provider authentication or authorization. Terminal OPERATE mode is also not approval; it only allows mutating requests to reach application policy.

The legacy scripted CLI does not yet route every live action through this operation controller. Do not describe the current scripted and interactive execution paths as identical. New shared execution work should converge beneath the interface boundary instead of making the terminal call the CLI secretly.

## Authorization and drift

Immediately before an execution permit is issued, the application recomputes the policy that created the plan.

For a network reconciliation operation, authorization reruns reconciliation. For an application workflow operation, authorization reruns the corresponding workflow policy and recomputes exact workflow targets when applicable.

Authorization fails if relevant immutable inputs no longer match, including when:

- desired state changed;
- observed state changed or became stale;
- reconciliation/workflow policy changed;
- selected action, risk class, mutation property, reason, or target scope changed;
- a current block appeared;
- a bound resource decision no longer hashes to the approved input;
- required approval is missing or does not match the immutable plan.

A previously approved action therefore cannot be forced through after state or policy drift. The operator must obtain current observations and create a new plan.

## Exclusive mutation claim

Only one mutating operation may hold workspace mutation authority at a time. Authorization creates `.synthran/operations/active-mutation.json` using exclusive file creation. The claim contains only the operation ID, plan digest, and timestamp.

A second mutating operation cannot be authorized while the claim exists. Read-only operations do not acquire it.

A successful mutation releases its exact claim. If an authorized mutation fails or is interrupted, the claim is retained and operation state becomes `recovery-required` unless clean rollback has been proven. SynthRAN does not infer that a failing command left provider state unchanged.

A recovery path must reconcile current state and release only the exact claim after safety is established.

## Event stream

Each operation emits ordered sanitized events from the validated vocabulary:

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

Events contain operation identity, sequence, timestamp, risk, mutation flag, plan digest, and bounded sanitized attributes. They do not contain SSH keys, provider passwords, raw command output, copied provider payloads, or arbitrary stderr.

The same event is appended to the operation-local log and workspace session event stream. The operation-local sequence is contiguous and starts at one.

See `docs/operation-events.md` for the event contract.

## Provider/domain executor contract

An `ExecutionPermit` is intentionally ephemeral. It identifies the operation, experiment, action kind, risk, mutation property, plan digest, issue time, and exact targets where present. It is the handoff between the control plane and a concrete executor.

Receiving a permit does not allow an executor to skip live gates. For example:

- a SLICES reservation/allocation adapter must still confirm current provider authority immediately before mutation;
- R2Lab control must still confirm the active lease before each physical-resource mutation;
- teardown may target only the exact resources authorized by the plan;
- an unknown or foreign resource remains non-mutable even if earlier evidence looked safe;
- an experiment executor must still prove the current network/run prerequisites at its live boundary.

The permit proves that local desired state, observed state, policy, approval, target scope, and concurrency policy agreed at authorization time. Live provider truth remains authoritative at the actual provider boundary.

## Current terminal boundary

The interactive terminal can create operation plans for all registered workflow commands, including `/run`, `/stop`, `/collect`, `/logs`, and `/down`. It does not yet have concrete provider/domain executors connected for those terminal plans.

A successful terminal plan therefore renders:

```text
Execution: not started
```

Do not document plan creation as live execution. The existing explicit scripted CLI remains the current operator path for live network/experiment/research actions until the shared executor layer is connected.
