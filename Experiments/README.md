# SynthRAN experiment suite

The `Experiments/` tree contains versioned scientific study designs built on the SynthRAN Ambient-IoT model and, where required, an accepted 5G testbed. Each experiment defines a research question, controlled intervention, measurement plan, inference boundary, and reproducibility requirements. Infrastructure provisioning remains outside the scientific layer.

## Scientific boundary

SynthRAN separates modeled Ambient-IoT behavior from measured 5G transport behavior:

- harvested energy, capacitor state, sensing, Ambient-IoT access, propagation, collision, decoding, and SIC are modeled unless an experiment explicitly states otherwise;
- a physical N300/N320 deployment carries the 5G gateway transport and does not convert the modeled Ambient-IoT link into a physical implementation;
- `deploy.sh` owns reservation, provisioning, repair, deployment, verification, and accepted infrastructure state;
- `experiment.sh` owns qualification, calibration, frozen experimental designs, confirmation campaigns, analysis, and scientific evidence;
- a scientific experiment may consume a compatible accepted deployment, but it must not mutate infrastructure merely to make a treatment pass.

Implemented capability, run-specific accepted behavior, and scientifically established results are treated as distinct claim levels.

## Studies

| ID | Study | Primary question | Evidence domain |
| --- | --- | --- | --- |
| Ex1 | [Energy correlation and burst formation](Ex1_Energy_Correlation_and_Burst_Formation/Ex1_Energy_Correlation_and_Burst_Formation.md) | Does cross-sensor energy correlation synchronize activation and change decoded traffic structure? | Modeled Ambient-IoT mechanism |
| Ex2 | [Causal 5G transport](Ex2_Flagship_Causal_5G_Transport/README.md) | Does release timing alone change application delivery for an event-identical workload? | Physical/accepted 5G transport |
| Ex3 | [MAC/SIC and delivered freshness](Ex3_MAC_SIC_and_End_to_End_Freshness/Ex3_MAC_SIC_and_End_to_End_Freshness.md) | Does improved reader-side decoding translate into improved end-to-end freshness? | Model + physical replay |
| Ex4 | [Sensor aggregation and UE scaling](Ex4_Sensor_Aggregation_and_UE_Scaling/Ex4_Sensor_Aggregation_and_UE_Scaling.md) | How do sensor population, gateway count, and connection count affect service capacity? | Model + physical replay |
| Ex5 | [Slice and QoS isolation](Ex5_Slice_and_QoS_Isolation/Ex5_Slice_and_QoS_Isolation.md) | Can a verified resource policy protect Ambient-IoT traffic from competing 5G load? | Physical 5G policy study |
| Ex6 | [N320 RF robustness and modeled coverage](Ex6_N320_RF_Robustness_and_Modeled_Coverage/Ex6_N320_RF_Robustness_and_Modeled_Coverage.md) | Does the transport effect persist across measured radio conditions? | Physical RF robustness + optional modeled sensitivity |
| Ex7 | [Causal gateway freshness mitigation](Ex7_Causal_Gateway_Freshness_Mitigation/Ex7_Causal_Gateway_Freshness_Mitigation.md) | Can a causal gateway policy reduce freshness violations at an explicit completeness/cost trade-off? | Physical replay + causal policy |

## Common research requirements

Unless an experiment explicitly defines a stricter rule, studies follow these principles:

1. **Prospective design.** Pilot/calibration data select operating points; confirmation treatments, seeds, exclusions, and principal contrasts are frozen before confirmatory execution.
2. **Independent experimental units.** Packets, sensors, time windows, or multiple transformations of one source trace are not counted as independent source replicates.
3. **Immutable identity.** Source revision, design contract, workload identity, deployment identity, and relevant dependency/image revisions are retained with the evidence.
4. **Matched interventions.** Comparisons preserve non-intervened variables wherever scientifically possible and record unavoidable treatment-mediated differences explicitly.
5. **Failure transparency.** Measurement-system invalidity, overload/service failure, intentional policy discard, and missing evidence are distinct outcomes and are never silently collapsed.
6. **No retrospective repair.** Scientific execution does not reconfigure the testbed to rescue a treatment. Infrastructure changes require a newly accepted deployment/configuration block.
7. **Claim discipline.** End-to-end measurements do not identify a radio, core, broker, or application bottleneck without aligned layer-specific evidence.
8. **Uncertainty reporting.** Results report effect estimates with uncertainty and distinguish statistical separation, practical relevance, and unresolved uncertainty.

The shared timing, receipt, AoI, clock, and experimental-unit conventions are summarized in [`MEASUREMENT_AND_INFERENCE.md`](MEASUREMENT_AND_INFERENCE.md). Study-specific documents remain authoritative when they define a stricter contract.

## Reproducibility

Scientific campaign output is written beneath:

```text
results/experiments/<experiment-id>/<campaign-id>/
```

A defensible result should be traceable from research question to versioned design, qualification/calibration evidence, frozen confirmation contract, model/workload evidence, accepted deployment identity when physical, experiment-time measurements, analysis, uncertainty, and archived immutable evidence.

Code availability alone is not evidence that a physical combination or scientific hypothesis has been validated. Current claims must be tied to retained run evidence.