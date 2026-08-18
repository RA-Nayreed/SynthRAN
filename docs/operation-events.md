# Structured operation event stream

SynthRAN exposes operation progress as a validated event stream rather than forwarding raw provider command output into the terminal.

Each operation has an append-only `.synthran/operations/<operation-id>/events.jsonl` stream. The same sanitized events are also appended to `.synthran/sessions/events.jsonl` for session-level rendering and audit.

## Event types

The control stream currently supports:

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

Stage events are emitted only while the operation state is `running`.

`stage.progress` contains only bounded progress metadata such as:

```json
{
  "stage": "network-verify",
  "current": "2",
  "total": "5"
}
```

Progress values originate as integers and must satisfy `0 <= current <= total` with `total > 0` before they are serialized as safe event attributes.

`stage.failed` contains a short safe failure code, for example `transport-error` or `lease-missing`. Raw SSH errors, command lines, provider payloads, tokens, addresses, or copied stderr are not accepted as failure-code attributes.

`state.changed` contains only a known SynthRAN observed-state dimension and one validated state:

```text
unknown
absent
pending
ready
degraded
failed
blocked
```

This makes events useful for terminal rendering without allowing provider text to become application state implicitly.

## Integrity checks

Every operation event carries:

- operation ID;
- contiguous operation-local sequence number;
- derived event ID `<operation-id>:<sequence>`;
- event type and timestamp;
- operation risk and mutation flag;
- immutable operation-plan SHA-256 digest;
- small validated string attributes.

`load_operation_events()` validates every line as an `OperationEvent`, requires a contiguous sequence, verifies the derived event ID, and checks event plan digest, risk, and mutation flag against the immutable `plan.json`.

A malformed or modified local event stream is rejected instead of partially rendered as trusted operation history.

## Terminal contract

The implemented terminal path obtains events through:

```text
TerminalSession.operation_updates()
-> ApplicationController.operation_events()
-> load_operation_events()
-> validated events.jsonl
-> terminal renderer
```

The terminal does not parse Ansible, POS, SSH, Kubernetes, R2Lab, experiment, or research stdout/stderr to infer operation progress.

Concrete executors may retain detailed private logs in existing provider/run evidence locations. Before exposing a transition or failure to the application stream, an executor maps it to a controlled stage name, progress counter, observed-state transition, or safe failure code.

Typical rendering can remain concise:

```text
[Open5GS] running
[Open5GS] 3/5
[Open5GS] ready
[gNB] running
[gNB] transport-error
```

The exact visual form belongs to the terminal layer. The event contract is independent of `prompt_toolkit` rendering.

## Current execution limitation

The event model and terminal rendering path are implemented, but an operation plan does not generate provider progress merely by existing. A concrete executor must first authorize the operation, perform the live/domain work, and emit structured events through the operation controller.

Terminal workflow plans currently stop at `Execution: not started` because those concrete terminal executor bindings are not yet connected. Do not treat an operation plan's initial `operation.started`/`plan.created` events as evidence that provider execution began.

## Interruption

User cancellation or an unexpected executor interruption uses `operation.interrupted`. If a mutating operation already holds its exclusive claim, interruption leaves that claim in place and operation state becomes `recovery-required`.

The terminal may stop rendering/waiting for progress, but it must not represent infrastructure as clean until reconciliation proves provider state and recovery releases the exact mutation claim.
