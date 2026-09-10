# Experiment readiness and execution contract

## How many experiments?

There are **seven experiment families**, not seven runs or seven promised papers.
Readiness tests are a prerequisite, not an eighth scientific experiment. Each
family contains controlled treatments, independent source seeds and repeated
transport runs; the final run count is set after an operating-point pilot.

| Family | Role | Primary question |
| --- | --- | --- |
| Energy correlation and burst formation | Core | Does shared harvesting synchronize reader output under matched marginal energy statistics? |
| Matched-trace physical 5G transport | Core | Does the ordering of identical upstream events change delivery under controlled competing traffic? |
| Gateway freshness mitigation | Core, subsequent implementation | Can an online gateway improve freshness without hiding delay, discarded updates or resource cost? |
| MAC/SIC and end-to-end freshness | Supporting | When do more reader decodes improve or harm downstream freshness? |
| Sensor aggregation and UE scaling | Supporting | Which resource limits many sensors per gateway and multiple gateways? |
| Slice/QoS isolation | Conditional supporting | Does verified uplink resource enforcement protect the telemetry workload? |
| N320 RF robustness and modeled coverage | Supporting | Does the transport result survive measured radio impairment, separately from modeled Ambient-IoT range? |

The strongest publication target is one coherent mechanism–transport–mitigation
study. The other families should resolve a specific uncertainty, not become a
large undirected configuration sweep. No code change establishes novelty or
guarantees publication.

## What this change qualifies

The implementation repairs the model-to-MQTT evidence path. It does not deploy
the N320, implement the proposed gateway policies, or prove slice enforcement.

| Layer | Implemented contract |
| --- | --- |
| Sensors and gateways | `devices` defines the modeled population; each sensor maps to one entry in `deployment.ues` through `gateway`. Extra UEs need not have sensors. |
| Sensing | Opportunities occur at `sensing_phase_ms + k * sensing_interval_ms`. Omitted phases are independently randomized from the seed. Unavailable or busy opportunities do not accumulate catch-up samples. |
| Harvesting | Explicit CSV timestamps and units, held/linear interpolation, per-sensor traces, and seeded common/independent lognormal inputs. `wpt_power_w` changes harvesting only. |
| Energy | One series-source circuit with blocking diode, leakage, constant-current state loads and explicit source/load/loss accounting. Listening and transmission consume energy. |
| Decoding | Full transmission energy must complete before decode. Actual overlapping airtime determines interference. Singletons must satisfy SINR; decoded signals retain uncancelled residual power. |
| Adaptive access | The next frame uses the preceding frame's slot outcomes, not cumulative historical failures. |
| Lineage | A generated sample has one stable event ID, generation time and sequence. Reader availability is after completed reception; multiple readers do not create duplicate MQTT events. |
| Bundles | Input evidence, resolved scenario, event bytes and implementation/dependency fingerprints are checksummed. Transformations retain the native trace and its manifest. |
| MQTT | Publication is independent of PUBACK timing. A queue-based callback handoff avoids publisher/callback lock inversion. Source binding, queue limits, planned releases, pre-publication timestamps and callback-entry receipt timestamps are recorded. |
| Measurement | Duplicate/invalid receipts are separated. Missing events remain in the deadline denominator. AoI is integrated over elapsed time, including silence and unknown initial state. |

One pending sample per sensor and one transmission attempt per generated sample
are the current data policy. There is no data retransmission policy. A command
is received instantaneously at its scheduled start if power and controller state
permit; waiting/listening still consumes energy. This is not a full command
waveform decoder. Adaptive slot occupancy is an ideal modeled observation, not
a calibrated energy detector. SIC uses minimum instantaneous SINR over the
packet, not a measured BLER or mutual-information link abstraction.

## Configuration and migration

Do not compare corrected results to old-main traces as if only a treatment
changed. Older sensing intervals, WPT overrides and SIC residual controls were
ineffective, and the energy and decode-time semantics differed. Regenerate a
complete campaign with one pinned implementation.

The default transmit duration is now 5 ms. A transmit duration longer than an RX
slot is rejected. The old sample `wpt_power_w` fields have been removed: leaving
the field absent derives harvesting from RF coverage, while providing it now
applies the requested control. Zero watts remains exactly zero. The UMa
below-10-m branch is clamped to its 10-m boundary; that is not validation of
near-field coverage.

`collision_window_ms` and `durations_ms.listening` are obsolete and trigger a
warning when supplied. Actual packet overlap controls decoding; periodic
opportunities and command slots determine listening time. Remove those fields
from treatment sweeps.

Example sensor mapping within an otherwise complete scenario:

```yaml
deployment:
  ues: [uesim01, uesim02]
devices:
  sensor-a: {gateway: uesim01, sensing_interval_ms: 1000, sensing_phase_ms: 125}
  sensor-b: {gateway: uesim01, sensing_interval_ms: 1000, sensing_phase_ms: 625}
```

Here `uesim02` is available for a separately controlled competing workload. Its
publisher emits no sensor events. Changing the UE list does not create or drop
modeled sensors. Interactive UE renaming preserves the sensor population and
remaps gateways positionally; removing a still-needed gateway requires an
explicit scenario edit.

For a matched-marginal energy-dependence study, replace `model.energy` with:

```yaml
energy:
  mode: environmental
  source: lognormal
  mean_power_w: 0.002
  coefficient_of_variation: 1.0
  sample_interval_s: 0.1
  correlation_time_s: 5.0
  correlation: common
  interpolation: hold
```

Use `independent` or a number in `[0, 1]` for the dependence treatment. A numeric
value is correlation in the latent Gaussian process, not Pearson correlation
of the resulting powers. The marginal law is matched in distribution, not
forced to have identical finite-run sample means. Retain and inspect the exact
per-sensor input CSVs, realized energy distributions and autocorrelations.
The example power is a synthetic pilot value, not a calibrated harvester.
Per-device `energy_mode` overrides take precedence; remove legacy WPT device
overrides when testing environmental power.

For recorded inputs use `trace`, `time_column`, `column`, `units`,
`interpolation`, `repeat` and optionally `period_s`. Recognized time columns are
`time_s`, `time_ms`, `time`, and `timestamp`; only `time_ms` is scaled from
milliseconds. Other timestamps must be numeric elapsed seconds. Samples must
start at zero and increase strictly. With repetition and no explicit period,
the period is the last timestamp plus the last sample interval. Independent
recorded inputs require an explicit `devices.<sensor>.energy.trace` for every
sensor; different filenames alone do not demonstrate statistical independence.

The circuit maps a power parameter to source voltage as
`V_source = sqrt(power_w * R_series)`. It is a source parameter, not a guarantee
of that much power reaching the capacitor; the resistor, diode, leakage and
voltage limit determine the delivered energy. Calibrate this mapping and the
load currents before making a hardware energy claim. `always_powered` holds
the capacitor rail fixed and reports the ideal external supply energy
separately; it is not a measured battery model.

## Local acceptance

```sh
python -m pip install -e '.[test]'
python -m unittest discover -s tests -v
python -m compileall -q synthran
bash -n deploy.sh
```

The MQTT integration tests start an ephemeral broker bound only to localhost.
They test real QoS 0 and QoS 1 bursts from two sensors on one gateway, SUBACK
readiness, byte identity, malformed-message handling and clean collector
shutdown. Without the `test` dependency these two integration tests are skipped;
a skipped test is not acceptance. No test contacts or provisions the testbed.

Tests cover hand-solvable capacitor energy balance, sensing period and fractional
phase, brownout rejection, SIC residual factors including zero and one, slot
boundaries, timestamp-aware harvesting, immutable interventions, corruption
rejection, separate ACK records and hand-integrated freshness examples.

## Freeze and intervene on one source workload

Use fresh output directories; existing bundles are not overwritten.

```sh
python -m Experiment.cli model run --config scenarios/reference.yml --output results/source/model
python -m Experiment.cli workload validate --source results/source/model
python -m Experiment.cli workload transform --source results/source/model --output results/permuted/model --variant gap_permutation --seed 101 --warmup-seconds 1
python -m Experiment.cli workload transform --source results/source/model --output results/periodic/model --variant periodic --warmup-seconds 1
```

These are command examples, not the final study duration or warm-up. The
intervention preserves pre-warm-up events, payload bytes, sensor/gateway/event
order, event count, measurement endpoints and full horizon. Gap permutation
also preserves the global inter-release-gap multiset. It is a finite gap-order
surrogate, not an independent renewal process. Periodic spacing is global;
neither intervention claims to preserve every sensor's gap distribution.

Keep native model time at 1×. A transformed trace retains its original
generation fields as provenance but is marked ineligible for physical AoI.
Use transport delay and deadline measures for that contrast. Evaluate physical
freshness and causal online mitigation on native arrivals.

Validate the prepared-workload deployment path without changing infrastructure:

```sh
./deploy.sh --config scenarios/reference.yml --prepared-workload results/permuted/model --dry-run
```

At the reviewed main commit `deploy.sh` is tracked with mode `100644`, so the
direct invocation needs an executable-mode correction by the repository owner.
The dry-run invocation was blocked by that permission in this review; only
shell syntax and the underlying import/validation functions were tested.

On an already qualified matching deployment, a separately authorized physical
or software replay uses `--workload-only --prepared-workload <bundle>` with the
same explicit scenario. This path imports the prepared bundle rather than
regenerating it. Sensor/gateway mapping and MQTT QoS, topic prefix and payload
size must match. Import validation precedes reservation or deployment changes.

`source-manifest.json` records hashes of the Python implementation and installed
model dependencies. It is an integrity record, not a signature, and does not
attest live container image IDs, runtime RAN configuration or clocks.

## Receiving endpoint and metric validity

The endpoint is the receiving application's MQTT callback, not broker ingress
or the radio boundary. QoS 1 records PUBACK separately; QoS 0 client-send
completion is not called an acknowledgement. Publication queue rejection is
retained as a failed submission. A reconnect may leave QoS 1 data in the client
queue; this is not a separate intentional replay or a fabricated receipt.

The collector writes its ready marker only after SUBACK and removes it on
disconnect. Publish and ACK records are append-only, and each replay refuses
to overwrite its publisher log. Shared starts must be timezone-aware and in
the future. Releases follow a monotonic schedule. A late start is rejected
instead of compressing overdue events into an unintended burst. The fixed
source horizon and drain apply even to a gateway with no sensor events.

Configure the measurement contract in the scenario before confirmation:

```yaml
measurement:
  warmup_seconds: 1
  deadline_seconds: 0.5
  age_limit_seconds: 2
```

Supply `clock_uncertainty_seconds` only from independently retained host clock
evidence. No default asserts clock validity. `clock_contract_satisfied` checks
the supplied bound, common-start agreement and observed nonnegative delays;
it does not measure synchronization itself. Delay quantiles without that
qualification are diagnostic clock differences, not validated one-way latency.
Negative delays are exposed, never clipped into successful measurements.

Deadline failure uses all planned events in the fixed measurement cohort,
including absent publications and receipts. The scalar is withheld until the
collector's final record extends beyond the source horizon plus the deadline
and the clock contract is satisfied. Keep the drain at least as long as the
deadline. Missing logs and unfinished runs must not become successful runs.

AoI never resets to an older or duplicate generation. Its time average and
time-weighted quantile integrate silence; unknown initial history is reported
explicitly. Uninitialized time counts as a freshness violation, and a whole-
window mean is withheld until initialized. Reader AoI uses modeled times;
application AoI additionally requires native timing and the external clock
contract. Retain per-sensor results and distributions across independent
source seeds rather than treating packets as independent replications.

## Physical acceptance still required

Before booking confirmation runs, demonstrate clean N320 attach and routing on
the chosen fixed core/RAN pair, including the selected MBIM/QMI data interface,
subscriber/session identity and broker source address. This change makes the
physical publisher interface configurable and verifies address membership; it
does not implement the separate N320 secondary-session work in draft PR #7.
Existing cluster identity checks are not proof of live physical IMSI or DNN.

Capture effective images/configuration and detect drift before and after each
run. Establish host clock bounds, pilot release jitter and queue occupancy,
and collect CPU, radio and user-plane evidence to identify the bottleneck.
Pin payload, QoS, bandwidth, scheduler and background-load generator throughout
a paired block. Use one gateway plus a proven competing-traffic UE before
claiming a larger physical UE population.

Slice names, DNNs and configured ratios alone are not uplink isolation evidence.
RF robustness needs measured physical SINR/BLER/RSRP and controlled attenuation
or placement, not a modeled Ambient-IoT distance sweep. Gateway pacing and
latest-update policies, automated competing traffic, campaign randomization,
calibrated harvesting, live image/configuration attestation and physical
qualification remain subsequent work. Stop a campaign if these required gates
are absent; report a failed qualification, not a positive scientific result.
