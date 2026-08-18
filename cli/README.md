# SynthRAN workbench prototype

This directory contains the replacement interactive terminal surface for SynthRAN.

## Checkpoint: static Ink shell

This checkpoint intentionally implements only the visual frame with mock state:

- one full-screen-style workbench surface;
- Access → Configure → Resources → Network → Run → Evidence phase strip;
- restrained neutral terminal styling derived from the selected editorial design principles;
- a Configure view showing radio, provider, R2Lab identity, and reservation state;
- explicit OBSERVE state;
- `q` to quit.

It intentionally does **not** include:

- Python/backend communication;
- SLICES, R2Lab, Docker, SSH, Kubernetes, or Ansible calls;
- configuration mutation;
- keyboard navigation between fields;
- operation planning or approval;
- legacy CLI removal.

The prototype is marked `private` in `package.json` to prevent accidental npm publication while the interface is under review.

## Local preview

```bash
cd cli
npm install
npm run typecheck
npm run build
npm start
```

The next checkpoint should be discussed before implementation. The intended next scope is interaction only: focus/navigation, selectors, screen switching, and an action palette, still against mock state.
