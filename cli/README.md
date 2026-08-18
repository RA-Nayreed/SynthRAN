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
- OBSERVE by default, with OPERATE available only on Configure for an explicit local write;
- an explicit read-only SLICES placement preview in Resources;
- completion markers derived from durable state rather than the selected screen;
- bounded local and provider-read timeouts, response-size checks, exact capability validation, and cancellation handling;
- `r` to reload local state;
- `q` or Ctrl+C to quit.

Creating a configuration writes only SynthRAN's local workspace. It creates a new active experiment record and preserves older experiments as history. Provider experiment binding remains empty, and the workbench does not create reservations, allocate resources, change provider state, deploy networks, start experiments, collect evidence, or tear resources down.

## Live resource preview

The Resources view performs no provider read on startup. Press Enter in Resources to request a current placement preview. The control service requires a fresh cached SLICES access record before it contacts POS, then performs exactly these read-only provider queries:

```text
pos calendar list --json
pos allocations list --json
```

The calendar and allocation results are combined into a fresh, complete snapshot of the reviewed SLICES compute catalog. A foreign reservation or allocation makes that node unsafe for automatic placement. The freshness boundary expires before any known reservation start or end that could change availability.

The resulting snapshot is passed to the same deterministic resource selector used by application planning. For a virtual configuration, the preview can select SLICES compute plus `virtual:rfsim`. A physical-radio configuration still fails closed because this interface does not provide live R2Lab radio/UE inventory.

The preview is placement evidence only. It is not reservation, allocation, ownership, or mutation authority. Leaving Resources, reloading, quitting, or changing the local experiment cancels or invalidates the current preview.

The control protocol is version 3. Its handshake declares local configuration writes and bounded provider reads while declaring provider mutation unavailable. The client requires the exact expected method set and fails closed if additional capabilities are advertised.

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

In Configure, use ↑/↓ to move focus and ←/→ to change intent or radio. Press `m` to switch from OBSERVE to OPERATE, then Enter on `Create configuration` to persist a new local experiment. Leaving Configure, reloading, or completing a write returns the workbench to OBSERVE.

In Resources, press Enter to perform the read-only SLICES inventory query and refresh the placement preview.

Set `SYNTHRAN_PYTHON` when the desired Python executable is not available as `python` in the current environment.
