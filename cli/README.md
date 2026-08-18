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
- completion markers derived from durable state rather than the selected screen;
- bounded startup, response-size, exact capability, protocol, and cancellation handling;
- `r` to reload local state;
- `q` or Ctrl+C to quit.

Creating a configuration writes only SynthRAN's local workspace. It creates a new active experiment record and preserves older experiments as history. Provider experiment binding remains empty, and the workbench does not create reservations, allocate resources, change provider state, deploy networks, start experiments, collect evidence, or tear resources down.

The control protocol is version 2. Its handshake explicitly allows the validated local configuration method while declaring provider mutation unavailable. The client requires the exact expected method set and fails closed if additional capabilities are advertised.

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

Set `SYNTHRAN_PYTHON` when the desired Python executable is not available as `python` in the current environment.
