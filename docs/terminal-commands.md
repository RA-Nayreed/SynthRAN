# Terminal command contract

SynthRAN terminal control uses an explicit slash-command vocabulary. The terminal does not interpret natural-language text as lifecycle control.

The registry is the single source of command names, fixed subcommands, risk class, mutation flag, help text, and terminal-mode policy.

## Commands

```text
/status
/inspect resources|network
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
/mode observe|operate
/help
/clear
/quit
```

There is no `/plan` command. Workflow commands themselves create immutable operation plans when current application policy permits them.

Inline provider/resource overrides are deliberately not accepted by lifecycle commands. For example, `/reserve sopnode-f2` and `/up --core-node sopnode-f1` are invalid terminal input. Resource choice comes from durable experiment configuration plus fresh provider inventory and the capability selector.

This prevents the terminal parser from becoming a second authority source.

## Risk classes

The command registry uses the same four risk categories consumed by the operation layer:

| Risk | Terminal meaning |
|---|---|
| R0 | local inspection or terminal-only action |
| R1 | live/read-only verification or evidence access |
| R2 | controlled mutation requiring standard operation approval |
| R3 | destructive mutation requiring destructive approval |

The exact risk belongs to the command registry and workflow/reconciliation policy. Do not maintain a second hand-written command-to-risk table elsewhere.

Examples from the current registry:

- `/status`, `/inspect`, `/config`, `/mode`, `/help`, `/clear`, and `/quit` are R0;
- `/verify`, `/collect`, and `/logs ...` are R1;
- `/reserve`, `/up`, `/recover`, `/run ...`, and `/stop` are R2;
- `/down` is R3.

`/down` represents explicit teardown and must still pass the operation plan, destructive approval, exact-target, ownership, drift, concurrency, and provider live-safety gates before any actual cleanup.

The terminal risk class does not itself authorize execution. It only determines whether a request may proceed from the terminal into application/operation policy.

## OBSERVE and OPERATE

A terminal session starts in `observe` mode.

In OBSERVE:

- R0 and R1 commands are accepted;
- every mutating command is rejected before it can reach the operation controller.

In OPERATE:

- R0 and R1 remain available;
- R2 and R3 requests may proceed to the application controller;
- immutable-plan, approval, freshness, ownership, drift, concurrency, and provider checks still apply.

Switching to OPERATE is not approval for a specific operation. It only enables the terminal to request a mutating operation.

## Strict parsing

`parse_command()` requires a leading `/`, uses shell-style quoting only for syntactic correctness, and validates the complete command against the registry.

Commands with fixed subcommands accept exactly one of the registered values. Commands without arguments reject all extra tokens.

Examples that fail closed:

```text
status
please deploy the network
/plan
/reserve sopnode-f2
/up --core-node sopnode-f1
/run arbitrary
/down all
/verify 12.1.1.2
```

The terminal therefore has no hidden shell command, natural-language fallback, or arbitrary provider/resource argument path.

## Help and completion

Help output is generated from the registry itself. The `prompt_toolkit` shell also derives fixed command/subcommand completion from the same registry, so parsing, help, and completion share one vocabulary.

Adding or removing a terminal command therefore requires changing the registry and its tests rather than editing a separate static help surface.

## Application routing

After parsing and terminal-mode policy, `TerminalSession` returns workflow commands as structured `CommandRequest` objects. `TerminalCommandRouter` maps those requests into `ApplicationController` calls.

The parser and session know nothing about SLICES, POS, SSH, Kubernetes, Ansible, R2Lab credentials, or legacy CLI argument construction. Provider-specific actions remain behind application, operation, resource, and provider-adapter boundaries.

Every registered workflow command now has a first-class application planning path. Planning is still distinct from provider execution: a successful plan currently renders `Execution: not started` until a corresponding terminal provider/domain executor is connected.

The terminal must not call the existing scripted CLI behind the scenes to cross that boundary.
