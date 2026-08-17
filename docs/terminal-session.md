# Session-first terminal controller

The terminal session layer turns strict slash commands into inline transcript output or structured application requests. It never invokes provider commands directly.

A terminal session starts in OBSERVE mode and keeps only lightweight in-memory UI state:

- current mode;
- whether the session is closed;
- visible transcript lines.

Durable experiment, operation, approval, observed-state, and provider authority remain outside the terminal session.

## Local commands

The session resolves commands that can be answered safely from application state or UI state:

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

The session does not pretend that routing is execution. A higher command router must map these requests to `ApplicationController`, operation policy, resource selection, and provider adapters.

In OBSERVE mode, mutating requests are rejected before they can become dispatch requests.

## Inline transcript

The session transcript contains only validated single-line entries classified as:

```text
command
result
system
error
```

Valid command entries are normalized from the strict parser, so arbitrary provider/resource overrides do not enter the transcript through the command line.

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

`TerminalSession.operation_updates()` reads the validated operation event stream through the application service and renders only events after a supplied sequence cursor.

This supports streaming terminal output such as:

```text
[path-check] running
[path-check] 2/3
[path-check] ready
Operation op-000041: completed
```

The session never parses raw provider stdout/stderr to create these lines. It renders only the structured event vocabulary validated by the operation layer.

## Shell boundary

This session controller is independent of the concrete input library. A prompt-toolkit shell can provide history, completion, key bindings, prompt styling, and asynchronous screen refresh while continuing to call `TerminalSession.submit()` and `operation_updates()`.

That keeps terminal ergonomics separate from lifecycle authority and provider execution.
