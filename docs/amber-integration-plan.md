# Amber integration plan

Goal: SynthRAN contains the full Amber Ambient-IoT engine as source, with no
runtime dependency on the separate `RA-Nayreed/Amber` repository, and
SynthRAN's simulation core orchestrates real Amber physics/MAC behavior
instead of a simplified re-implementation.

```text
SynthRAN/
├── amber/            ← full, faithful Amber engine (this PR)
├── third_party/amber ← LICENSE + SOURCE.json provenance (this PR)
├── synthran/
│   ├── model/         ← legacy Amber-derived copies + SynthRAN-original
│   │                     EnergyWorkloadModel (unchanged in this PR)
│   └── amber/          ← SynthRAN <-> Amber integration layer (future)
```

## Status

- [x] **Phase 1 — Vendor Amber.** `amber/` added at repo root, copied from
      `RA-Nayreed/Amber@08dd6bd` (main, 2026-08-28). Preserved as-is except one
      tracked compatibility patch (optional `matplotlib` import in
      `amber/propagation.py`) recorded in `third_party/amber/SOURCE.json`.
- [x] **Phase 2 — Packaging.** `pyproject.toml` now discovers `amber`/`amber.*`
      alongside `synthran`/`synthran.*`, so `from amber import backscatter,
      bsengine, capacitor, controller, energy, packet_analysis, propagation,
      radiodevices` works with no path hacks or git submodules.
- [ ] **Phase 3 — Consolidate `synthran/model/*`.** Replace the legacy
      Amber-derived copies (`backscatter.py`, `bsengine.py`, `capacitor.py`,
      `controller.py`, `packet_analysis.py`, `propagation.py`,
      `radiodevices.py`) with re-exports from `amber.*`, then remove the
      compatibility shim once nothing references the old paths.
      `synthran/model/energy.py` and `engine.py` are SynthRAN-original and are
      out of scope for this step.
- [ ] **Phase 4 — Replace `EnergyWorkloadModel` with `AmberRunner`.** This is
      the substantial change: today `EnergyWorkloadModel` (a hand-rolled
      RC-charge/discharge integrator) is the only thing that actually runs on
      `synthran model run` — none of the vendored Amber classes are wired into
      it yet. Swapping in a real `simpy`-driven Amber simulation changes the
      physics, timing model, and output shape, and has no existing test
      coverage to validate against (neither repo currently has automated
      tests). This needs its own design/PR with fixtures before landing.
- [ ] **Phase 5 — `synthran/amber/runner.py`.** Centralized `AmberRunner`
      building topology, coverage, energy sources, capacitors, controllers,
      backscatter modules, and BS behavior from a scenario dict.
- [ ] **Phase 6 — Expand scenario schema** to configure Amber natively
      (topology/placement, sectorized base station, propagation model,
      capacitor/controller electrical parameters, protocol selection,
      SIC/receiver parameters) instead of the current simplified per-device
      knobs.
- [ ] **Phase 7 — Protocol modules** (`amber/protocols/` or
      `synthran/amber/protocols.py`) so `protocol.type` in the scenario
      selects behavior without SynthRAN source changes. Note: upstream Amber
      does not currently expose a `protocols` module — this is new work, not
      a vendoring step.
- [ ] **Phase 8 — Normalize Amber outcomes**, don't recompute them (collision/
      SIC/capture decisions from Amber are authoritative).
- [ ] **Phase 9 — Separate Amber-layer loss from 5G-transport loss** in
      reconciliation output (opportunities → energy-suppressed → transmitted →
      radio/collision loss → decoded → 5G input → received → transport loss).
- [ ] **Phase 10 — Keep Amber execution on the orchestration side**, not
      inside the UE container (unchanged from current architecture).
- [ ] **Phase 11 — Richer evidence directory** under `results/<run>/model/`
      (topology/coverage/bs-tx/bs-rx/node-tx/node-rx/controller/capacitor
      traces + summary.json) alongside the existing `events.jsonl`/
      `suppressed.jsonl`.
- [ ] **Phase 12 — Parity tests** comparing `RA-Nayreed/Amber` directly against
      the vendored `amber/` copy (same commit/seed/scenario/trace →
      identical placement, propagation, capacitor trajectories, controller
      states, TX/RX records, collision/SIC outcomes, BS counters). Requires
      building test scaffolding from scratch, since none exists today in
      either repository.
- [ ] **Phase 13 — Purge** `synthran/model/engine.py` and the legacy
      Amber-derived files under `synthran/model/`, only after Phase 12 parity
      tests pass and downstream consumers (`deploy.sh`, `synthran/results`,
      `synthran/workload/replay.py`) are migrated to the new evidence shape.

## Explicitly out of scope / not being resurrected

Per the agreed design, this integration should not reintroduce: a
SynthRAN-specific rewrite of Amber physics under `synthran/model/*`, a runtime
`git clone` of Amber, `sys.path` hacks, or hard-coded single-configuration
wrappers (e.g. fixed device counts/slot counts baked into code instead of
scenario config).
