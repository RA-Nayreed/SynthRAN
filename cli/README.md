# SynthRAN workbench

This directory contains the new interactive terminal surface for SynthRAN.

The current implementation provides:

- one full-screen-style workbench surface;
- Access → Configure → Resources → Network → Run → Evidence navigation;
- restrained neutral terminal styling derived from the selected editorial design principles;
- keyboard navigation with Tab, Shift+Tab, and direct numeric shortcuts;
- an action palette opened with `/`;
- editable in-memory configuration controls for radio, provider binding, SSH identity, and reservation duration;
- explicit OBSERVE and OPERATE presentation;
- mock-only views for access, resources, network, run controls, and evidence;
- `q` or Ctrl+C to quit.

The current implementation intentionally does **not** include:

- Python/backend communication;
- SLICES, R2Lab, Docker, SSH, Kubernetes, or Ansible calls;
- persistent configuration mutation;
- provider resource mutation;
- legacy CLI removal.

The npm package is marked `private` in `package.json` to prevent accidental publication while the interface is under development.

## Local preview

```bash
cd cli
npm install
npm run typecheck
npm run build
npm start
```
