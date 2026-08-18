# SynthRAN workbench

This directory contains the interactive terminal surface for SynthRAN.

The current implementation provides:

- one terminal workbench with Access → Configure → Resources → Network → Run → Evidence navigation;
- keyboard navigation with Tab, Shift+Tab, direct numeric shortcuts, and an action palette opened with `/`;
- sanitized local state loaded through the versioned SynthRAN control service;
- cached SLICES and R2Lab access freshness without exposing key paths or fingerprints;
- durable experiment configuration, lifecycle, observations, next action, and block reasons;
- completion markers derived from durable state rather than the selected screen;
- bounded startup, response-size, capability, and protocol validation;
- local creation of one active experiment when the workspace does not already have one;
- validated intent and radio selectors whose canonical desired state is built in Python;
- OBSERVE by default and `m` to enable OPERATE only on the local creation screen;
- `r` to reload local state;
- `q` or Ctrl+C to quit.

Local experiment creation writes only the SynthRAN workspace. The workbench does not create provider reservations, allocate resources, bind provider experiments, deploy networks, start experiment workloads, collect evidence, or tear resources down.

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

Set `SYNTHRAN_PYTHON` when the desired Python executable is not available as `python` in the current environment.
