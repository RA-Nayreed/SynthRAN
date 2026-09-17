# Experiment 5: protection of Ambient-IoT traffic under competing 5G load

## Objective

Test whether a verified 5G resource-control policy protects Ambient-IoT gateway freshness from competing UE traffic, and identify the layer responsible for any observed protection.

The experiment distinguishes **logical slice identity** from **measured resource isolation**. Different S-NSSAI/DNN values, subscriber profiles, or successful registration do not by themselves prove scheduler, queue, or capacity isolation.

## Scope and claim boundary

The victim is a frozen Ambient-IoT-derived gateway workload transported through an accepted 5G deployment. The experiment studies protection of that transport workload; it does not establish physical Ambient-IoT RF isolation.

A RAN-isolation claim requires a RAN mechanism that is both configured and observed in the relevant traffic direction. If the active mechanism is instead core/N6 policing, shaping, UPF resource separation, or host-level isolation, the claim must name that layer explicitly.

## Research questions

- **Q1:** At equal competing traffic volume, do bursty interferer patterns produce more victim deadline/freshness violations than smooth patterns?
- **Q2:** Does logical slice separation alone change the victim outcome when service parameters are otherwise neutralized?
- **Q3:** Does a verified resource-control policy reduce victim degradation, at what cost to the competing flow, and through which measured mechanism?

The primary direction is uplink because the gateway sends telemetry toward N6. A downlink-only scheduling feature cannot be reported as validated uplink protection.

## Capability and configuration gates

Before confirmation:

1. create an experimental service profile in which 5QI, AMBR, and other QoS fields are equal across control arms unless a field is the declared intervention;
2. prove the victim and competitor UE data paths, S-NSSAI/DNN identities, session addresses, and actual publisher routes;
3. identify one enforceable protection mechanism in the exact deployed build;
4. demonstrate that the mechanism changes the intended resource/policing behavior under a simple known traffic pair;
5. retain the configured policy and corresponding runtime evidence.

For srsRAN-based studies, documented scheduler controls such as PRB policies are candidate mechanisms, but YAML acceptance is not proof of enforcement. The exact build and the relevant uplink behavior must be qualified with measured allocations or other direct scheduler evidence.

If only a core/N6 policer can be demonstrated, complete a core-queue study under that name rather than relabeling it as RAN slice isolation.

## Fixed roles and traffic

- **UE A:** victim gateway carrying the frozen Ambient-IoT-derived workload.
- **UE B:** competing-flow generator through the same accepted cell/path context.

Use homogeneous UE hardware and fixed radio conditions where possible. Otherwise treat modem/location differences as blocks and retain them in provenance.

Within a comparison, freeze victim source, payload bytes, gateway/connection count, replay schedule, broker/sink placement, and logging. Construct smooth and bursty competitor treatments with equal event/byte volume and horizon; freeze burst duration, duty cycle, and peak rate prospectively.

Record **offered**, **admitted**, and **delivered** competitor traffic separately. A configured nominal rate is not evidence of the actual offered load.

## Policy arms

| Arm | Configuration | Interpretation |
| --- | --- | --- |
| I0 | Same slice, equal QoS, no explicit protection | Shared-resource baseline |
| I1 | Different S-NSSAI/DNN, equal QoS/resource policy | Logical-separation control |
| I2 | Different slices plus one verified protection mechanism | Protection mechanism under test |

Measure a no-competitor baseline for each policy arm because the policy itself may alter victim latency or throughput. Configuration changes form distinct attested blocks and must not reuse an accepted identity that no longer matches the active policy.

For a scheduler reservation, freeze a feasible victim guarantee or competitor cap from independent pilot work and retain configured plus measured resource shares. For a policer, retain placement, rate, burst allowance, shaping/dropping behavior, and counters.

## Campaign design

1. Qualify both UE paths and neutral service profiles.
2. Determine the victim's baseline requirement and an independent competitor-load transition.
3. Prove the selected protection mechanism on a simple traffic pair.
4. Freeze two nonzero background levels around the selected transition, plus unloaded baselines.
5. Use independent victim source realizations and pair the same source/background realization across policy arms.
6. Compare smooth and bursty competitor patterns at each nonzero load.
7. Randomize workload order inside configuration blocks and counterbalance configuration-block order across sessions.

A planning loaded matrix using ten source realizations is:

```text
3 policy arms × 2 traffic patterns × 2 nonzero loads × 10 sources = 120 replays
```

Unloaded baselines add:

```text
3 policy arms × 10 sources = 30 replays
```

for 150 planned replays before capability pilots. Final duration and source count must be frozen from independent precision/runtime planning rather than adjusted after confirmation begins.

## Outcomes

Primary victim outcomes:

- deadline-failure probability;
- fraction of time above the native freshness/AoI limit.

Supporting victim outcomes include p95 scheduled-release-to-application delay, delivery by drain deadline, starvation intervals, and conditional transport latency.

For outcome `Y` where lower is better, define within-policy degradation relative to the policy's own unloaded baseline:

\[
I_{policy,load}=Y_{policy,load}-Y_{policy,no\ competitor}.
\]

Then compare:

- `I_I1 - I_I0` for logical-separation effect;
- `I_I2 - I_I1` for protection beyond identity separation.

Report competitor throughput/service cost, measured resource share, and fairness beside victim benefit. Protection obtained by effectively starving the competing flow is a trade-off, not a free isolation gain.

## Mechanism evidence

Where available, retain aligned evidence from the layer being claimed:

- uplink radio allocations, HARQ/BLER, scheduler/resource counters;
- RLC/PDCP queue evidence;
- UPF/policer queue/drop counters;
- host CPU and socket/drop indicators;
- broker/receiver load.

If the deployed build does not expose the required field, mark mechanism attribution unresolved. Do not substitute assumed values.

## Falsification and validity threats

- I1 may perform like I0 because logical slice naming alone does not reserve resources.
- I2 may offer no measurable benefit or may move the bottleneck to a shared core, host, or broker.
- A victim benefit can be caused by reducing admitted competing traffic rather than by scheduler isolation; offered/admitted/delivered traffic and layer counters must expose this.
- Unequal QoS fields, modem/RF conditions, or background traffic volume can confound the slice-policy intervention.

Either a null protection result or a relocated bottleneck is scientifically meaningful when the policy is demonstrably active and uncertainty is adequate.

## Reproducibility and claim discipline

Retain exact experimental profiles, accepted deployment/configuration identity, UE bindings, policy state, source/background identities, treatment order, runtime mechanism evidence, exclusions, and analysis outputs.

Shared timestamp, receipt, AoI, clock, experimental-unit, and failure-taxonomy conventions are defined in [`../MEASUREMENT_AND_INFERENCE.md`](../MEASUREMENT_AND_INFERENCE.md).

Claims are limited to the measured load, traffic pattern, radio state, policy, software/hardware revisions, and observation horizon. Do not infer complete isolation, URLLC guarantees, standardized QoS compliance, or O-RAN/RIC control from application-level evidence alone.

## Completion criteria

The experiment is complete when:

1. both UE data paths and the neutral control profile are verified;
2. the protection mechanism is shown active in the relevant direction;
3. I0/I1/I2 are runtime-distinct and reproducibly attested;
4. every assigned run has a documented disposition;
5. victim benefit and competitor cost are analyzed together with uncertainty;
6. claimed mechanism attribution is supported by aligned layer evidence or explicitly left unresolved.
