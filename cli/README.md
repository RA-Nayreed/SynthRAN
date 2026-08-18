# SynthRAN workbench

This directory contains the interactive terminal surface for SynthRAN.

The workbench is organized around operator-owned objects rather than internal controller concepts:

```text
Setup → Resources → Network → Experiment → Data
```

It keeps the underlying safety model intact while presenting only the action that makes sense for the current state.

## Setup

Setup shows and edits the concrete configuration used by SynthRAN:

- saved controller profile and SLICES user;
- SLICES project;
- an existing SLICES experiment selected and bound explicitly;
- Open5GS core;
- srsRAN gNB;
- srsUE;
- Virtual / RFSIM or Physical / R2Lab radio selection;
- automatic or manual SLICES compute placement;
- explicit core and RAN nodes when manual placement is selected;
- reservation duration.

An initialized workspace may switch to another saved controller profile before the active network configuration is bound or started. SynthRAN verifies the selected profile's SLICES project access before changing the durable workspace profile. An unbound local configuration is only deactivated; its experiment directory remains preserved as history.

For automatic SLICES placement, the reviewed selector chooses safe resources from fresh provider inventory and currently prefers `sopnode-f2` for core and `sopnode-f3` for RAN when available. Manual placement stores the selected core/RAN node IDs directly in the experiment desired state. Planning still verifies those exact resources against fresh provider inventory and ownership before any provider mutation.

R2Lab slice and SSH identity details are shown only when Physical / R2Lab is selected. Physical execution is not connected yet.

Creating a new network configuration creates a new local `sran-YYYYMMDD-NNN` experiment record and preserves prior records as history. Provider experiment creation remains outside SynthRAN; Setup discovers existing SLICES experiments and binds one explicitly.

## Resources and Network

Resources and Network do not present a permanent command strip. The workbench derives the next concrete action from current state.

Typical progression is:

```text
CONFIGURED     → Reserve resources
RESERVED       → Allocate nodes
ALLOCATED      → Prepare nodes
PREPARED       → Deploy 5G network
NETWORK_READY  → Verify 5G path
PATH_PROVEN    → Open Experiment
```

`Recover allocation` appears only when the current state actually requires the supported allocation recovery path.

Cleanup is also contextual. When appropriate, `s` exposes either `Release allocation` or `Stop network and release allocation`. The current executor preserves the active reservation during this cleanup.

There is no global OBSERVE / OPERATE switch. Safety remains enforced by the operation engine instead:

1. Enter creates one immutable action plan from fresh provider state.
2. The exact action and targets are displayed.
3. Enter records the required confirmation when the action mutates provider state.
4. Enter executes the already confirmed action separately.
5. Provider authority, ownership, drift and exact plan-bound inputs are rechecked immediately before mutation.

Destructive cleanup receives destructive confirmation through the same explicit plan → confirm → execute sequence. `x` cancels a planned or confirmed action before live execution begins.

Running provider work remains non-interruptible from the workbench until executor-specific safe cancellation exists.

## Network display

The Network view describes the actual accepted stack rather than implementation prose:

```text
Core / Open5GS
RAN / srsRAN
UE / srsUE
Radio / RFSIM
PDU session
UPF
5G path
```

Live execution in this surface currently supports only the accepted virtual RFSIM path. Physical R2Lab execution, research execution and data collection remain outside this executor.

## First use

When no persistent workspace exists, Setup can reuse an existing controller profile or create a new profile with a SLICES username and optional R2Lab slice plus SSH identity. Provider access is verified before persistent local state is written. The operator also chooses the reservation default and whether later resource placement starts in automatic or manual mode.

Initialization does not reserve, allocate, deploy or create the SLICES provider experiment.

## Local preview

Use the locked SynthRAN environment, which includes the Node.js runtime required by the workbench:

```bash
conda activate synthran
cd cli
npm install
npm run typecheck
npm run build
npm test
npm start
```

General controls:

- `Tab` / `Shift+Tab` navigate sections;
- `1`–`5` jump directly to Setup, Resources, Network, Experiment and Data;
- `/` opens the action palette;
- `r` reloads current local state;
- `q` or Ctrl+C quits when no live provider action is running.

In Setup:

- ↑/↓ moves focus;
- ←/→ changes profile candidate, radio, placement, manual core/RAN nodes, reservation duration, or provider selection;
- Enter on Profile verifies and switches the selected saved profile;
- Enter on New network config persists the selected radio and placement, including exact core/RAN nodes in manual mode;
- Enter can also save defaults, load provider experiments, or bind the selected provider experiment.

In Resources or Network:

- Enter advances the current contextual action through plan → confirm → execute;
- `s` prepares the currently available stop/release action;
- `x` cancels a prepared action before execution.

Set `SYNTHRAN_PYTHON` when the desired Python executable is not available as `python` in the current environment.
