# Experiment 6: N320 RF robustness and modeled Ambient-IoT coverage

## Objective

Determine whether the flagship traffic-structure effect persists across measured 5G radio conditions and identify the physical link conditions under which the gateway transport stops meeting its declared delivery/freshness requirement.

A secondary, explicitly separate study may evaluate modeled Ambient-IoT reachability under stated propagation and energy assumptions. Physical 5G RF robustness and modeled Ambient-IoT coverage are different evidence domains and must not be merged into one coverage claim.

## Evidence domains

| Link | Evidence source | Defensible outcome |
| --- | --- | --- |
| Modeled sensor → modeled Ambient-IoT reader | Energy/controller/backscatter/channel simulation | Service/coverage probability conditional on the stated model and its validation |
| Physical gateway UE → gNB/N320 | Accepted physical 5G transport with measured RF state | Transport robustness under the recorded physical conditions |

A successful MQTT receipt over N320 does not validate the modeled sensor RF link budget. RFSIM cannot provide physical RF-coverage evidence.

## Research questions and hypotheses

- **F1:** At fixed competing offered load, weaker measured 5G uplink conditions change delivery/freshness outcomes and may amplify the penalty of native burst timing relative to an event-identical periodic control.
- **F2:** Part of an apparent RF effect may be explained by reduced available service capacity; a separately prespecified capacity-normalized comparison can test what remains after adjusting load.
- **F3 (optional modeled extension):** Ambient-IoT service probability depends jointly on energy margin, command reception, backscatter reception, and contention; a path-loss-only range sweep is insufficient.

F1 does not assume monotonic conditional latency. Weak conditions may selectively remove difficult traffic, so deadline failures, outages, and all-sensor freshness remain primary evidence.

## Physical prerequisites

Before RF treatments are assigned, retain and verify:

- accepted deployment identity and exact RAN/core/radio revisions;
- runtime image digest and rendered radio parameters;
- stable UE registration and expected PDU session/DNN/S-NSSAI;
- attested publisher interface/source address and reachable receiving application;
- experiment-time RF and network telemetry with timestamps.

Freeze core, RAN version, channel bandwidth, numerology, scheduler policy, TDD configuration, UE hardware/firmware, power-control configuration, antenna arrangement, and N6/application placement inside the primary comparison.

Reference configuration values are provenance facts, not proof of live hardware state. Runtime state must be recorded from the actual accepted deployment.

## Establishing the RF intervention

The study must first identify what can actually be controlled:

| Available capability | Procedure | Claim boundary |
| --- | --- | --- |
| Characterized conducted path with controllable attenuation | Record calibrated path/attenuation and randomize or balance attenuation blocks | Causal effect of the specified attenuation in that setup |
| Controlled over-the-air positioning | Record position, orientation, environment, and repeated channel measurements | Effect of the specified placement intervention |
| Fixed remote UE positions without controllable path | Group repeated workloads by measured channel state | Conditional robustness; no randomized-RF causal claim |

Do not emulate physical attenuation by silently changing gains or dropping packets in software. gNB transmit gain, receiver gain, path loss, and UE uplink condition are not interchangeable interventions.

Use an independent pilot to define **good**, **transitional**, and **weak-but-operational** states from measured radio/service behavior. Prefer direct uplink evidence such as PUSCH SINR/BLER/retransmission information when the running stack exposes it. Downlink RSRP or UE-reported quantities must be labeled by direction and source rather than used as generic uplink quality.

Registration or service failure at an assigned treatment is a genuine outcome when the study requirement includes access/service availability. Measurement-system failure is a separate invalid-run category.

## Physical workload and campaign

Use prespecified common-harvesting E-knee source realizations from the qualified model. Compare each native trace with an event-identical periodic timing control that preserves event count, bytes, order, topics, first/last measurement release, and fixed horizon.

Calibrate transport service at good RF, then freeze two absolute competing offered rates: a low rate and a rate near the good-RF operating transition. Keep these **absolute offered rates** unchanged across RF treatments for F1. If a weaker RF state becomes overloaded at the same offered rate, that is part of the intervention rather than a reason to retune the treatment after seeing results.

A planning confirmation matrix is:

| Factor | Levels |
| --- | --- |
| Independent source seeds | 10 |
| Timing | Native, periodic |
| Physical RF state | Good, transitional, weak-but-operational |
| Competing offered load | Low, near good-RF transition |
| Planned physical replays | **120** |

Randomize/balance RF-block order across sessions and randomize paired workload order within a block. Do not collect all weak-RF observations only at the end of the campaign. Measure RF state during each replay rather than relying on an earlier label.

F2 may add a smaller prespecified subset in which competing load is adjusted to a matched measured utilization fraction at each RF state. This is a different causal question and must not replace the fixed-rate F1 design retrospectively.

## Outcomes and analysis

Primary outcomes:

- application deadline failure;
- p95 scheduled-release-to-application delay.

Analyze the native-minus-periodic effect within each source/RF/load block, then estimate how that effect changes across RF states with source/session-level uncertainty.

Supporting evidence includes offered/delivered competing load, radio/service metrics, registration/PDU failures, reconnects, outage duration, application delivery by drain, and native-trace AoI/freshness outcomes for the full sensor population.

Do not compute the main result only from surviving good-RF intervals. Finite-horizon overloaded conditions are overload experiments and do not establish stationary queue-delay distributions.

Three chosen RF states establish robustness at those states; they do not constitute a general geographic coverage map.

## Optional modeled Ambient-IoT coverage sensitivity

The optional model study must use a propagation abstraction appropriate to the intended geometry/frequency and state what has actually been calibrated. If relevant RF measurements are unavailable, report a **model sensitivity analysis**, not physical coverage.

Document forward command and reflected-data paths, antenna assumptions, receiver sensitivity/noise, fading/shadowing, energy conversion, and whether RF harvesting shares the same propagation path. Avoid double-applying path loss or omitting a required return path.

A starting design may use five prespecified distance/path-loss levels, two environmental-energy margins, and 20 independent realizations, producing 200 model runs before additional controls. Pair exogenous realizations across distance levels and keep sensor count, contention policy, sensing law, population geometry, and correlation regime fixed.

Define service over a fixed observation window and classify insufficient energy, command-reception failure, collision/decoding failure, starvation, and successful updates separately. A single successful packet at a distance is not evidence of reliable coverage.

A downstream 5G replay can quantify application consequences of a modeled source trace; it cannot turn a simulated sensor-range curve into a physical Ambient-IoT range measurement.

## Falsification and validity threats

- Native timing may show no additional penalty at weak RF.
- RF-state differences may be explained primarily by changed available capacity rather than by timing interaction.
- The competitor's own RF state can alter scheduler/resource competition and must be controlled or retained as a block.
- Uncontrolled time/session drift can be confounded with RF blocks.
- A gain change or downlink metric can be incorrectly interpreted as uplink path attenuation if evidence direction is not explicit.

## Reproducibility and evidence

Retain exact physical treatment definition, runtime radio/RAN/core provenance, UE bindings, measured RF evidence, source/background identities, session/block order, clock evidence, run dispositions, and analysis outputs.

Shared timestamp, receipt, AoI, clock, experimental-unit, and failure-taxonomy conventions are defined in [`../MEASUREMENT_AND_INFERENCE.md`](../MEASUREMENT_AND_INFERENCE.md).

## Completion criteria

The physical study is complete when every assigned replay has a disposition, source/timing matching is verified, the RF treatment or observed-state grouping is supported by experiment-time evidence, and application outcomes are analyzed jointly with radio/service observations.

If controllable RF intervention is unavailable, complete the conditional robustness analysis and state the additional apparatus or positioning evidence required for a causal physical coverage claim. The optional modeled study remains separately labeled and interpreted.
