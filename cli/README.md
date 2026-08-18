# SynthRAN workbench

This directory contains the interactive terminal surface for SynthRAN.

The current implementation provides:

- one terminal workbench with Access → Configure → Resources → Network → Run → Evidence navigation;
- keyboard navigation with Tab, Shift+Tab, direct numeric shortcuts, and focused configuration controls;
- an action palette opened with `/`;
- first-use workspace configuration inside the same workbench instead of a separate prompt sequence;
- sanitized discovery of existing controller profiles and private SSH identity references;
- read-only SLICES and optional R2Lab verification before first-use state is persisted;
- local state loaded through the versioned SynthRAN control service;
- cached SLICES and R2Lab access freshness without exposing key paths or fingerprints;
- editable reservation-duration and placement defaults stored atomically in the local workspace;
- durable experiment configuration, lifecycle, observations, next action, and block reasons;
- creation of a new immutable local experiment from the Configure view;
- virtual, physical, and automatic radio selection with compatible experiment intent choices;
- read-only discovery of SLICES experiments in the verified workspace project;
- explicit one-time binding of a selected, reverified SLICES experiment to the active local experiment;
- OBSERVE by default, with OPERATE available only on Configure for explicit local writes;
- completion markers derived from durable state rather than the selected screen;
- bounded startup, response-size, exact capability, protocol, provider-read, and cancellation handling;
- `r` to reload local state;
- `q` or Ctrl+C to quit.

## First use

When no persistent workspace exists, the workbench opens Configure immediately. It can reuse an existing controller profile or create a new profile with a SLICES username and optional R2Lab slice plus SSH identity. SSH discovery reads only enough of files directly below `~/.ssh` to identify private-key files; the workbench receives normalized identity references, not key contents or fingerprints.

Initialization verifies SLICES project access and, when configured, the R2Lab SSH gateway before writing the profile, workspace, or access evidence. The existing workspace initialization service retains rollback behavior if verification or persistence fails. Reservation duration and placement are chosen in this view and become the workspace defaults.

First-use initialization is a local write and therefore requires OPERATE. Provider verification performed during initialization is read-only; no reservation, allocation, experiment creation, or deployment is performed.

## Configure

Creating an experiment configuration writes only SynthRAN's local workspace. It creates a new active experiment record and preserves older experiments as history. Reservation duration and placement can be changed independently through `Save workspace defaults`; those changes preserve workspace identity, project, profile, and strict ownership policy.

Provider discovery verifies the configured SLICES project before listing experiments. Binding rechecks the selected experiment and then records that exact name locally. A different provider experiment cannot replace an existing binding on the same local experiment.

Provider discovery is available in OBSERVE because it is read-only. First-use initialization, workspace-default updates, experiment creation, and provider binding require an explicit switch to OPERATE. Reloading, navigating away from Configure, or completing a local write returns the workbench to OBSERVE.

The workbench does not create SLICES experiments, reservations, allocations, or resources. It does not change provider state, deploy networks, start experiments, collect evidence, or tear resources down.

The control protocol is version 4. Its handshake declares the exact supported local-write and provider-read methods while declaring provider mutation unavailable. The client requires the exact expected method set and fails closed if additional capabilities are advertised. Earlier contract versions remain frozen in `contracts/`.

The npm package is marked `private` in `package.json` to prevent accidental publication while the interface is not yet released.

## Local preview

Run from the SynthRAN repository or any directory inside an initialized workspace:

```bash
cd cli
npm install
npm run typecheck
npm run build
npm test
npm start
```

Before a workspace exists, Configure supports:

- ↑/↓ to move focus;
- typing on profile, project, username, and R2Lab-slice rows when those rows are editable;
- ←/→ to choose an existing profile or a new profile, enable R2Lab, select a discovered SSH identity, adjust reservation duration, and change placement;
- `m` to switch between OBSERVE and OPERATE outside text-entry rows;
- Enter on `Initialize` in OPERATE to verify access and persist the local workspace.

After initialization, Configure supports:

- ↑/↓ to move focus;
- ←/→ to change intent, radio, reservation duration, placement, or a loaded provider selection;
- `m` to switch between OBSERVE and OPERATE;
- Enter on `Save workspace defaults` in OPERATE to persist reservation and placement choices;
- Enter on `Create configuration` in OPERATE to persist a new local experiment;
- Enter on `Provider experiment` in OBSERVE or OPERATE to load SLICES experiments when no provider is bound;
- ←/→ to select one of the loaded provider experiments;
- Enter on `Bind provider` in OPERATE to reverify and record the selected provider experiment locally.

Set `SYNTHRAN_PYTHON` when the desired Python executable is not available as `python` in the current environment.
