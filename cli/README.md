# SynthRAN workbench

This directory contains the interactive terminal surface for SynthRAN.

The current implementation provides:

- one terminal workbench with Access → Configure → Resources → Network → Run → Evidence navigation;
- keyboard navigation with Tab, Shift+Tab, direct numeric shortcuts, and focused configuration controls;
- an action palette opened with `/`;
- local state loaded through the versioned SynthRAN control service;
- cached SLICES and R2Lab access freshness without exposing key paths or fingerprints;
- durable experiment configuration, lifecycle, observations, next action, and block reasons;
- creation of a new immutable local experiment from the Configure view;
- virtual, physical, and automatic radio selection with compatible experiment intent choices;
- read-only discovery of SLICES experiments in the verified workspace project;
- explicit one-time binding of a selected, reverified SLICES experiment to the active local experiment;
- on-demand read-only resource observations in the Resources view;
- OBSERVE by default, with OPERATE available only on Configure for explicit local writes;
- completion markers derived from durable state rather than the selected screen;
- bounded startup, response-size, exact capability, protocol, provider-read, and cancellation handling;
- `r` to reload local state;
- `q` or Ctrl+C to quit.

Creating a configuration writes only SynthRAN's local workspace. It creates a new active experiment record and preserves older experiments as history. Provider discovery verifies the configured SLICES project before listing experiments. Binding rechecks the selected experiment and then records that exact name locally. A different provider experiment cannot replace an existing binding on the same local experiment.

Provider discovery and resource observation are available in OBSERVE because they are read-only. Creating a local configuration or recording a provider binding requires an explicit switch to OPERATE. Leaving Configure, reloading, or completing either write returns the workbench to OBSERVE.

The Resources view separates the reviewed capability catalog from live provider truth. SLICES allocation ownership is displayed only when it can be observed from POS. Nodes absent from the allocation list remain `unknown`; they are not treated as available because allocation state alone does not prove calendar availability. The SLICES provider view therefore remains incomplete. R2Lab resources remain unobserved until a resource-specific live source is connected. `virtual:rfsim` is the only locally known available resource. Incomplete provider state cannot authorize selection or reservation.

The workbench does not create SLICES experiments, reservations, allocations, or resources. It does not change provider state, deploy networks, start experiments, collect evidence, or tear resources down.

The control protocol is version 4. Its handshake explicitly allows the known local-write and provider-read methods while declaring provider mutation unavailable. The client requires the exact expected method set and fails closed if additional capabilities are advertised. Earlier contract versions remain frozen in `contracts/`.

The npm package is marked `private` in `package.json` to prevent accidental publication while the interface is not yet released.

## Local preview

Run from an initialized SynthRAN workspace so the Python control service can resolve the local source of truth:

```bash
cd cli
npm install
npm run typecheck
npm run build
npm test
npm start
```

In Configure:

- use ↑/↓ to move focus;
- use ←/→ to change intent, radio, or a loaded provider selection;
- press `m` to switch between OBSERVE and OPERATE;
- switch to OPERATE, then press Enter on `Create configuration` to persist a new local experiment;
- press Enter on `Provider experiment` in OBSERVE or OPERATE to load SLICES experiments when no provider is bound;
- use ←/→ to select one of the loaded provider experiments;
- switch to OPERATE, then press Enter on `Bind provider` to reverify and record the selected provider experiment locally.

In Resources, press Enter to refresh the conservative read-only inventory. The view does not reserve or select anything.

Set `SYNTHRAN_PYTHON` when the desired Python executable is not available as `python` in the current environment.
