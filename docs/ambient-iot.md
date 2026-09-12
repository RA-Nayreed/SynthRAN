# Native Ambient-IoT architecture

SynthRAN's Ambient-IoT scientific model lives in `synthran/model/`. It
originated from Amber commit `08dd6bd445e607ad3accf4e9a2dff51a499ebdf9`
and is now maintained as part of SynthRAN. Attribution, license, and import
provenance are recorded in `third_party/amber/`.

`AmbientIoTRunner` constructs nodes, sectors, coverage calculations,
capacitors, controllers, backscatter modules, and `BSBehavior`. The scenario
selects `broadcast`, `broadcast_sic`, `unicast`, `framed_aloha`, or
`adaptive_aloha`. The model's received packets and collision/SIC decisions are
authoritative Ambient-IoT outcomes. Only decoded packets become `events.jsonl`
records for later 5G/MQTT replay.

Each model run writes the resolved scenario and lineage manifest beside native
evidence under `model/ambient_iot/`. The simulation runs on the orchestrator
before 5G replay; UEs receive the immutable replay trace and lightweight
publisher runtime.

The implementation is not maintained as an upstream Amber mirror. Changes are
made directly in `synthran/model/`, while SynthRAN-specific orchestration and
protocol integration live primarily under `synthran/ambient_iot/`. The
historical Amber record remains immutable provenance rather than an update
mechanism.

Runnable protocol scenarios live beside the integration code under
`synthran/ambient_iot/examples/`.
