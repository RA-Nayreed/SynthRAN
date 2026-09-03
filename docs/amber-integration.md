# Embedded Amber architecture

SynthRAN vendors the complete Amber package at `amber/`, pinned by
`third_party/amber/SOURCE.json`. The vendored directory remains upstream code;
SynthRAN-specific behavior belongs in `synthran/amber/`.

`AmberRunner` constructs native Amber nodes, sectors, coverage calculations,
capacitors, controllers, backscatter modules, and `BSBehavior`. The scenario
selects `broadcast`, `broadcast_sic`, `unicast`, `framed_aloha`, or
`adaptive_aloha`. Amber's received packets and collision/SIC decisions are the
authoritative Ambient-IoT outcomes. Only decoded packets become `events.jsonl`
records for later 5G/MQTT replay.

Each model run writes the resolved scenario and Amber provenance beside native
evidence under `model/amber/`. The simulation runs on the orchestrator before
5G deployment; UEs only receive the immutable replay trace and lightweight
publisher runtime.

To update Amber, copy `amber/` from the desired upstream commit, update
`third_party/amber/SOURCE.json`, reapply the documented optional-matplotlib
patch, and run the parity and integration tests.
