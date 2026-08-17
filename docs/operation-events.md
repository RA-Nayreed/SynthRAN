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

`stage.progress` contains only:

```json
{
  "stage": "network-verify",
  "current": "2",
  "total": "5"
}
```

Progress values are integers and must satisfy `0 <= current <= total` with `total > 0`.

`stage.failed` contains a short safe failure code, for example `transport-error` or `lease-missing`. Raw SSH errors, command lines, provider payloads, tokens, addresses, or copied stderr are not accepted as failure codes.

`state.changed` contains only a known SynthRAN observed-state dimension and one of the validated states:

```text
unknown
absent
pending
ready
degraded
failed
blocked
```

This makes the event useful for terminal rendering without allowing provider text to become application state implicitly.

## Integrity checks

Every operation event carries:

- operation ID;
- contiguous operation-local sequence number;
- derived event ID `<operation-id>:<sequence>`;
- event type and timestamp;
- operation risk and mutation flag;
- immutable operation-plan SHA256 digest;
- small validated string attributes.

`load_operation_events()` validates every line as an `OperationEvent`, requires a contiguous sequence, verifies the derived event ID, and checks the event plan digest, risk, and mutation flag against the immutable `plan.json`.

A malformed or modified local event stream is rejected instead of partially rendered as trusted operation history.

## Terminal contract

The terminal should obtain operation events through `ApplicationController.operation_events()` and render them as transcript updates. It does not need to parse Ansible, POS, SSH, Kubernetes, or R2Lab command output to understand operation progress.

Provider executors may still retain detailed private logs in their existing provider-specific evidence locations. Before exposing a status transition or failure to the application stream, the executor maps it to a controlled stage name, progress counter, state transition, or safe failure code.

Typical rendering can therefore remain concise:

```text
[Open5GS] running
[Open5GS] 3/5
[Open5GS] ready
[gNB] running
[gNB] transport-error
```

The exact visual form belongs to the terminal layer. The event contract is independent of prompt-toolkit rendering.

## Interruption

User cancellation or an unexpected executor interruption uses the existing `operation.interrupted` event. If a mutating operation already holds its exclusive claim, interruption leaves that claim in place and operation state becomes `recovery-required`.

The terminal may stop waiting for progress, but it must not render the infrastructure as clean until reconciliation proves the provider state and recovery releases the exact claim.
