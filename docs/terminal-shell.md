# Interactive terminal shell

Running `synthran` with no arguments opens the session-first interactive terminal. Supplying any explicit arguments preserves the existing scripted CLI unchanged.

```text
synthran                     # interactive terminal
synthran doctor ...          # scripted CLI
synthran network verify ...  # scripted CLI
```

The executable is a thin launcher. `synthran/cli.py` remains the single registration and implementation source for the scripted command tree; the launcher only chooses interactive versus scripted mode from whether argv is empty.

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

The current router maps application-modeled lifecycle requests as follows:

| Terminal command | Application action |
|---|---|
| `/reserve` | plan the current `reserve` reconciliation step |
| `/up` | plan exactly one current progression step: `reserve`, `allocate`, `prepare`, or `up` |
| `/verify` | plan the current read-only `verify-path` step |
| `/recover` | plan one explicit `recover-*` step when reconciliation exposes exactly one |
| `/config resources` | render durable workspace resource policy |
| `/config experiment` | render the active experiment projection |

Resource-bound planning requires a fresh `ResourceInventory` supplied through an inventory adapter. If no fresh adapter is configured, the router fails closed before creating an operation.

`/up` never silently turns path verification into a mutation. When the network is ready and `verify-path` is next, it instructs the operator to use `/verify`.

## Provider execution boundary

Planning is not execution. A planned operation prints its operation ID, risk, approval requirement, and `Execution: not started`.

The terminal does **not** tunnel a workflow into the legacy CLI to make it appear implemented. That would bypass the shared application, immutable operation plan, approval, ownership, freshness, and provider-adapter boundaries.

The following registered commands still require dedicated application/domain executors before the interactive terminal may run them:

```text
/down
/run baseline|congestion
/stop
/collect
/logs network|open5gs|ue
```

Until those executors exist, the router returns an explicit error and confirms that no provider action was taken. The existing explicit scripted CLI remains available for operator-run live workflows.

## Transcript and progress

Router output is copied into the visible `TerminalSession` transcript only after it passes the terminal line-safety contract. Application operation events are then rendered through `TerminalSession.operation_updates()` from the validated structured event journal.

The shell does not parse raw SSH, POS, Kubernetes, Ansible, R2Lab, or provider stderr to determine progress.

## Exit and interruption

- `/quit` closes only the terminal session.
- EOF closes the terminal session.
- Ctrl-C cancels the current input line and keeps the session open.
- `/clear` clears the visible terminal display/transcript only; durable experiment and operation evidence is untouched.

Provider-operation cancellation remains an operation-executor concern and must preserve the existing recovery-required semantics once mutation authority has been acquired.
