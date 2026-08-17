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

Inline provider/resource overrides are deliberately not accepted by lifecycle commands. For example, `/reserve sopnode-f2` and `/up --core-node sopnode-f1` are invalid terminal input. Resource choice comes from durable experiment configuration plus fresh provider inventory and the capability selector.

This prevents the terminal parser from becoming a second authority source.

## Risk classes

The command registry uses the same four risk classes as the operation layer:

| Risk | Terminal meaning |
|---|---|
| R0 | local inspection or terminal-only action |
| R1 | live/read-only verification or evidence collection |
| R2 | controlled mutation requiring operation approval |
| R3 | explicit destructive mutation requiring destructive approval |

`/down` is R3. It represents explicit teardown and must still pass the operation plan, destructive approval, exact-target, ownership, and provider live-safety gates before any actual cleanup.

The terminal risk class does not itself authorize execution. It only determines whether a request may proceed from the terminal into the application/operation policy boundary.

## OBSERVE and OPERATE

A terminal session starts in `observe` mode.

In OBSERVE:

- R0 and R1 commands are accepted;
- every mutating command is rejected before it can reach the operation controller.

In OPERATE:

- R0 and R1 remain available;
- R2 and R3 requests may proceed to the application controller;
- all normal immutable-plan, approval, freshness, ownership, concurrency, and provider checks still apply.

Switching to OPERATE is not approval for a specific operation. It only enables the terminal to request a mutating operation.

## Strict parsing

`parse_command()` requires a leading `/`, uses shell-style quoting only for syntactic correctness, and validates the complete command against the registry.

Commands with fixed subcommands accept exactly one of the registered values. Commands without arguments reject all extra tokens.

Examples that fail closed:

```text
status
please deploy the network
/reserve sopnode-f2
/up --core-node sopnode-f1
/run arbitrary
/down all
/verify 12.1.1.2
```

The terminal therefore has no hidden shell command, natural-language fallback, or arbitrary argument path.

## Help

Help output is generated from the registry itself. Adding or removing a command changes the parsed vocabulary and the help output together.

A later interactive shell should render `render_help()` inline in the transcript rather than maintaining a separate static help screen.

## Interface boundary

The command parser knows nothing about SLICES, POS, SSH, Kubernetes, Ansible, R2Lab, or provider credentials. After parsing and terminal-mode policy, a higher terminal session layer maps the structured `CommandRequest` into `ApplicationController` calls.

Provider-specific commands remain behind application, operation, resource, and provider-adapter safety boundaries.
