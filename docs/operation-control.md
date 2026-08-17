# Operation control boundary

SynthRAN separates reconciliation from execution. Reconciliation determines the next safe action from durable desired state and current observed state. The operation controller turns exactly one of those actions into a durable, reviewable operation and only then issues an ephemeral execution permit.

The controller does not replace provider-specific safety checks. SLICES, POS, SSH, Kubernetes, Ansible, and R2Lab adapters must still verify their own live ownership and authority immediately before each resource mutation.

## Operation lifecycle

One operation uses a workspace-wide non-reusable ID such as `op-000041`. The existing workspace registry allocates the ID before extra operation records are written, so an interrupted creation attempt still consumes its identifier.

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
└── sessions/events.jsonl             # append-only cross-operation transcript
```

`operation.json` is the durable identity record allocated by the registry. `plan.json` is immutable. `state.json` is the current local operation status. `approval.json` is immutable approval evidence. Event logs contain sanitized control events, not provider command output.

## Immutable plan binding

An operation plan contains the selected reconciliation action together with SHA256 digests of:

- the detailed desired experiment state;
- the reconciled observed-state snapshot;
- the reconciliation report.

The plan itself has a SHA256 digest over all immutable plan fields. Loading a plan recomputes that digest and rejects modified content.

This binding prevents approval for one state from being silently reused after the requested network, observed resources, or policy result changes.

## Approval policy

Risk classes have one meaning across the terminal and scripted interfaces:

| Risk | Meaning | Approval |
|---|---|---|
| R0 | local/read-only inspection | none |
| R1 | live read-only verification | none |
| R2 | controlled resource mutation | explicit standard approval |
| R3 | explicitly destructive mutation | explicit destructive approval |

Approval records are bound to the exact operation ID, plan digest, and risk class. R3 cannot use a standard R2 approval.

Approval is a local operator-consent record, not a replacement for provider authentication or authorization.

## Authorization and drift

Immediately before an execution permit is issued, the controller runs reconciliation again using the supplied desired and observed state at the current time. Authorization fails if:

- any desired-state field changed;
- any observed-state field changed;
- the observations have become stale and reconciliation therefore changes;
- the selected action, risk class, mutation property, or reason changed;
- a current block appeared;
- required approval is missing or does not match the immutable plan.

This makes a previously approved action unusable after state drift. The operator must obtain new observations and create a new operation instead of forcing the old one through.

## Exclusive mutation claim

Only one mutating operation may hold workspace mutation authority at a time. Authorization creates `.synthran/operations/active-mutation.json` using exclusive file creation. The claim contains only the operation ID, plan digest, and timestamp.

A second mutating operation cannot be authorized while the claim exists. Read-only operations do not acquire it.

A successful mutation releases its exact claim. If an authorized mutation fails or is interrupted, the claim is retained and operation state becomes `recovery-required`. SynthRAN does not guess that a failed command left the provider unchanged. A later recovery service must reconcile live provider state and release only the exact claim after safety is established.

## Event stream

Each operation emits ordered sanitized events such as:

```text
operation.started
plan.created
approval.requested
approval.granted
operation.authorized
operation.completed
operation.failed
operation.interrupted
recovery.required
```

Events contain operation identity, sequence, timestamp, risk, mutation flag, plan digest, and small sanitized attributes such as action kind or approval mode. They do not contain SSH keys, provider passwords, raw command output, PDU addresses, reservation payloads, or other copied provider data.

The same event is appended to the operation-local log and the workspace session transcript. The operation-local sequence is contiguous and starts at one.

## Provider executor contract

An `ExecutionPermit` is intentionally ephemeral. It identifies the operation, experiment, action kind, risk, mutation property, plan digest, and issue time. It is the handoff between the control plane and a provider executor.

Receiving a permit does not allow an adapter to skip its own gates. For example:

- a SLICES reservation or allocation executor must still confirm current provider ownership before mutation;
- R2Lab control must still confirm the active lease immediately before each power action;
- cleanup may target only resources proven to belong to the authorized operation;
- an unknown or foreign resource remains non-mutable even if an earlier observation looked safe.

The execution permit therefore proves that local intent, observed state, reconciliation, approval, and concurrency policy agreed at authorization time. Live provider truth remains authoritative at the actual mutation boundary.
