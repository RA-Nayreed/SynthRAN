# Experiment 2: scientific rationale, calibration evidence, and interpretation

## Research motivation

Experiment 2 asks whether **the timing of the same decoded Ambient-IoT events changes downstream application delivery under controlled competing traffic**. Its scientific role is to connect an upstream energy-and-access model to measured 5G gateway transport without changing event identity or count.

The motivating mechanism is straightforward: clustered releases can create transient queueing and deadline failures that are invisible to an average-rate workload. The study therefore separates event identity from event timing and compares matched timing transformations on the same source realization.

Ambient-IoT devices may depend on harvested energy and may not always have enough stored energy to communicate. Harvesting may be continuous or incidental, so intermittent or correlated activity is plausible but not universal. See [3GPP TS 22.369, section 4.2](https://www.etsi.org/deliver/etsi_ts/122300_122399/122369/19.03.00_60/ts_122369v190300p.pdf).

Correlated harvesting also has an established research basis. Abad, Gunduz, and Ercetin study energy-harvesting nodes with correlated energy arrivals sharing a random-access destination. That work establishes correlated energy as a legitimate networking variable; it does not validate SynthRAN's capacitor model or prove that its decoded traffic matches a deployed Ambient-IoT population. The contribution here is the controlled connection between that modeled timing mechanism and downstream 5G application delivery. See [Abad et al., *Energy harvesting wireless networks with correlated energy sources*](https://arxiv.org/abs/1902.04890).

## Source evidence from Experiment 1

The retained [Experiment-1 results](../Ex1_Energy_Correlation_and_Burst_Formation/RESULTS.md) summarize 210 model runs: seven conditions and 30 source seeds. At the historical energy knee:

| Condition mean | Independent harvesting | Common harvesting |
| --- | ---: | ---: |
| Active fraction | 45.4% | 44.5% |
| Realized power correlation | 0.001 | 0.961 |
| Decoded events per second | 12.628 | 11.294 |
| Fano factor | 0.584 | 13.391 |
| Inter-event-gap coefficient of variation | 0.922 | 6.508 |
| Collision rate | 7.30% | 15.33% |

The active fractions are similar while the decoded event process is much more bursty under common harvesting. Directly comparing common versus independent traces in transport would still be confounded because event counts differ. Experiment 2 therefore transforms each retained event set internally so event identity and count remain fixed while release timing changes.

A newer committed Experiment-1 campaign under [`evidence/20260913T185453409916Z`](../Ex1_Energy_Correlation_and_Burst_Formation/evidence/20260913T185453409916Z/analysis/summary.json) selected 64 sensors rather than 32. Its reported knee-independent versus knee-common means are respectively: active fraction 45.15% versus 44.67%; decoded events/s 23.178 versus 18.935; Fano factor 0.539 versus 22.075; gap CV 0.886 versus 8.947; and collision exposure 13.97% versus 27.45%.

These retained model summaries motivate the timing intervention, but neither establishes an Experiment-2 transport effect. The actual Ex2 source cohort is defined by the prepared campaign identity and frozen source bundles.

## Hypotheses and estimands

For outcome `Y`, source seed `i`, and load level `l`, define:

```text
NP(i,l) = Y(native,i,l) - Y(periodic,i,l)
NR(i,l) = Y(native,i,l) - mean[Y(gap_r1,i,l), Y(gap_r2,i,l)]
```

For the principal lower-is-better outcomes, positive values mean a native-timing penalty.

- **T1 — total timing effect:** native timing differs from periodic release. This measures the effect of replacing the observed release structure with an evenly spaced schedule over the same endpoints.
- **T2 — gap-order effect:** native timing differs from the mean of two exact-gap permutations. This tests sensitivity to temporal arrangement beyond the aggregate gap histogram.
- **T3 — load interaction:** the native timing effect changes with controlled competing load.

The direction remains empirical. A shuffle can preserve or create clusters by chance, and transport scheduling can favor different timing structures under different conditions. A narrow interval near zero limits the supported effect; a wide interval is inconclusive. Statistical separation from zero must not be relabeled practical importance or equivalence without an independently justified margin.

## Why the timing controls are informative

Each source seed supplies four timing arms:

| Arm | Timing operation | Interpretation |
| --- | --- | --- |
| `native` | Original completed-reader-decode availability times | Reference source process |
| `periodic` | Evenly spaced measurement releases retaining the same endpoints | Timing regularization |
| `gap_permutation_r1` | Deterministic permutation of measured gaps | Gap order changed, gap multiset retained |
| `gap_permutation_r2` | Independent deterministic permutation of the same gaps | Second matched control realization |

Event identity/order, sensor identity, payload bytes, MQTT topic, event count, source horizon, gateway role, and first/last measurement release remain fixed. Warm-up is retained separately.

Permuting gaps changes where fixed events occur in time, including per-sensor update schedules. It is therefore a constrained timing surrogate rather than a single-parameter intervention on one correlation coefficient.

The method follows the general logic of surrogate time-series analysis: rearrange observed values without replacement to retain their distribution while changing temporal order. Two permutations are useful matched controls but are not a sufficient ensemble for a conventional per-trace 5% surrogate-rank test; with two controls, the minimum one-sided rank-test p-value is 1/3. Scientific replication comes from independent source seeds, not from treating the two permutations as new source replicates. See [Schreiber and Schmitz, *Surrogate time series*](https://arxiv.org/pdf/chao-dyn/9909037).

A simple queue illustrates why ordering can matter even when count and gap histogram are unchanged. Suppose five jobs each require 100 ms of service:

| Schedule | Arrival times, ms | Gaps, ms | Maximum waiting time |
| --- | --- | --- | ---: |
| Clustered | 0, 0, 0, 300, 600 | 0, 0, 300, 300 | 200 ms |
| Rearranged | 0, 0, 300, 300, 600 | 0, 300, 0, 300 | 100 ms |

Count, endpoints, average rate, and gap histogram are identical. Only order changes. For an ideal single server this is captured by:

```text
W(next) = max(0, W(current) + service_time - next_gap)
```

This example explains the mechanism; it is not a fitted model of the 5G testbed or a prediction of effect size.

## Confirmation structure

The frozen design is:

```text
30 source seeds × 4 timing arms × 3 calibrated loads = 360 replays
```

Three 10-seed sessions organize execution and drift checks; they do not increase the independent sample size. Timing-arm order is deterministically randomized within each source/load block, and drift sentinels are interleaved at the frozen cadence.

The physical campaign uses an already accepted deployment. One verified UE carries the workload and another carries paced UDP competition to an N6-side sink. Core, RAN, radio, nodes, service profile, UE roles, and deployment identity are retained as provenance.

Using two UEs does not by itself prove that both flows contend at the same radio scheduler or bottleneck. Scheduler/resource attribution requires aligned runtime evidence. The gateway topology is relevant to indirect Ambient-IoT communication, but the replay does not implement or certify the full standardized indirect communication mode described by TS 22.369. See [section 4.4](https://www.etsi.org/deliver/etsi_ts/122300_122399/122369/19.03.00_60/ts_122369v190300p.pdf).

## Outcome interpretation

The principal transport delay is application receipt time minus scheduled release time. It includes publisher lateness, client queuing, network transport, broker processing, and subscriber delivery. Publisher release error is reported separately so scheduling delay is not hidden inside later transport delay.

The p95 is conditional on receipts observed by the fixed drain deadline. Missing events do not receive zero delay. The complementary 0.5-second deadline-failure fraction includes events that arrive late or remain missing, preventing selective receipt survival from concealing overload.

MQTT QoS 1 PUBACK records a client-to-broker protocol exchange; it does not establish receiving-application delivery. UDP competitor loss, TCP recovery, MQTT acknowledgement, and application deadline failure are therefore different measurements. See [OASIS MQTT 3.1.1](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html).

Age of Information measures time since generation of the freshest received status rather than transit time alone. Long gaps between fresh updates can increase age even when individual packet delivery is fast. See [Yates and Kaul, *The Age of Information: Real-Time Status Updating by Multiple Sources*](https://arxiv.org/pdf/1608.08622).

SynthRAN retains generation timestamps, but some timing transformations can schedule release before modeled generation. Generation-based AoI is invalid for such transformed arms and is guarded by the transformation's `generation_age_valid` contract.

The 0.5-second application deadline and secondary 2-second age threshold are study parameters, not standards-compliance thresholds. TS 22.369 includes application-dependent examples such as 1-second tracking latency and 20–30-second room-environment monitoring latency, but those refer to different service boundaries and use cases. See [TS 22.369 tables 6.3-1 and 6.4-1](https://www.etsi.org/deliver/etsi_ts/122300_122399/122369/19.03.00_60/ts_122369v190300p.pdf).

## Retained calibration pilot

The retained pilot calibration produced three 10-second repeats at each requested rate through 50 Mbps. Median end-to-end UDP delivery ratios were:

| Requested payload rate | Median UDP delivery ratio |
| ---: | ---: |
| 5 Mbps | 0.998754 |
| 10 Mbps | 0.998056 |
| 15 Mbps | 0.998045 |
| 20 Mbps | 0.997999 |
| 25 Mbps | 0.998038 |
| 30 Mbps | 0.998072 |
| 40 Mbps | 0.997704 |
| 50 Mbps | 0.997696 |

The original selector defined ABOVE as the first ascending valid rate with median delivery ratio below 0.98, NEAR as its predecessor, and BELOW as the preceding level. No tested point crossed the threshold.

Therefore the retained pilot establishes only that the sampled loss boundary was not bracketed through the requested 50-Mbps point under that run. It does **not** establish 50-Mbps path capacity, absence of queueing, radio saturation, or any T1–T3 result.

The terms BELOW/NEAR/ABOVE are deliberately operational labels around an end-to-end UDP loss boundary, not claims about a physical radio-capacity knee. Tail-drop loss can occur after queueing delay has already increased, and network-characterization guidance treats delay, jitter, and loss as distinct evidence. See [RFC 7567](https://www.rfc-editor.org/rfc/rfc7567.html) and [RFC 7928](https://www.rfc-editor.org/rfc/rfc7928.html).

## Design revision 2

Revision 2 retains the 0.98 crossing criterion while extending the prespecified ascending grid to:

```text
5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120, 150, 200, 250 Mbps
```

Each repeat must achieve 95–105% of its requested application-payload rate with zero sender errors. A nominal 200-Mbps treatment generated at 90 Mbps cannot become evidence about a 200-Mbps offered condition.

UDP has no congestion control, so a paced UDP source is useful for prescribing offered competition but differs fundamentally from an adaptive TCP competitor. Requested, achieved, and received rates must therefore remain separate. See [RFC 8085](https://www.rfc-editor.org/rfc/rfc8085.html).

Revision 2 also retains every completed probe before stopping, including invalid repeats and unbracketed sweeps. The sweep stops after the first qualifying crossing and its predecessor structure are established. If the generator is invalid or the crossing cannot provide BELOW/NEAR/ABOVE, confirmation remains blocked.

Because the calibration rule changed after the pilot, the revised design starts a new campaign rather than retrospectively reinterpreting the stopped pilot under different rules.

## Statistical interpretation

The full study contract freezes source cohort, deployment, load levels, sessions, outcomes, exclusion rules, and statistical settings.

Eligibility is contrast-specific. An invalid permutation arm does not discard an otherwise valid native-periodic comparison. For each estimable outcome, report included seeds and exclusion reasons. Measurement-system invalidity is distinct from a genuine overload failure.

Paired percentile-bootstrap intervals use source-seed differences, averaging permutation outcomes within source/load before source-level resampling. The available cohort size of 30 seeds is not itself a power calculation. A prospective precision or power analysis requires an independently justified practical effect and plausible between-seed variance.

Reported intervals are pointwise 95% intervals without multiplicity adjustment. They must not be interpreted as familywise-confirmed evidence across all outcomes, loads, and contrasts.

The bootstrap treats source-seed differences as independent and does not automatically propagate shared session drift or clock uncertainty. Clock probes bound offset only at their measurement times; extending that evidence across a replay assumes sufficiently stable clocks. Drift sentinels improve observability but do not prove continuous stationarity.

## Claim boundary

A positive `NP` supports a conditional native-versus-periodic replay-timing penalty. A positive `NR` additionally supports sensitivity to temporal arrangement beyond the exact gap multiset. Positive load interactions support amplification over the calibrated load range.

Those conclusions remain conditional on the modeled decoded source cohort, accepted deployment, treatment validity, and measurement contract. Physical harvesting, Ambient-IoT RF propagation, access collisions, and reader decoding occur upstream of the physical replay and are not manipulated by Experiment 2.

End-to-end timing evidence alone cannot locate a bottleneck. A claim specifically about radio queueing requires aligned sender pacing, workload overlap, scheduler/resource observations, retransmissions, endpoint CPU/socket-drop evidence, and other relevant diagnostics.

Future extensions may use queue/delay-aware calibration, adaptive competing traffic, shared-versus-isolated slice policies, larger surrogate ensembles, or source timing validated against measured harvesting traces. Such extensions should be declared prospectively rather than selected after confirmation results are known.

## References

1. 3GPP/ETSI. *Service requirements for Ambient power-enabled IoT*. TS 22.369 / ETSI TS 122 369 V19.3.0, Release 19, January 2026. [Specification](https://www.etsi.org/deliver/etsi_ts/122300_122399/122369/19.03.00_60/ts_122369v190300p.pdf).
2. M. Salehi Heydar Abad, D. Gunduz, and O. Ercetin. *Energy harvesting wireless networks with correlated energy sources*. IEEE WCNC 2016; author manuscript deposited 2019. [Paper](https://arxiv.org/abs/1902.04890).
3. T. Schreiber and A. Schmitz. *Surrogate time series*. Physica D 142, 346–382, 2000; author manuscript 1999. [Paper](https://arxiv.org/pdf/chao-dyn/9909037).
4. F. Baker and G. Fairhurst. *IETF Recommendations Regarding Active Queue Management*. RFC 7567, July 2015. [RFC](https://www.rfc-editor.org/rfc/rfc7567.html).
5. N. Kuhn et al. *Characterization Guidelines for Active Queue Management (AQM)*. RFC 7928, July 2016. [RFC](https://www.rfc-editor.org/rfc/rfc7928.html).
6. L. Eggert, G. Fairhurst, and G. Shepherd. *UDP Usage Guidelines*. RFC 8085, March 2017. [RFC](https://www.rfc-editor.org/rfc/rfc8085.html).
7. A. Banks and R. Gupta, editors. *MQTT Version 3.1.1*. OASIS Standard, 29 October 2014. [Specification](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html).
8. R. D. Yates and S. K. Kaul. *The Age of Information: Real-Time Status Updating by Multiple Sources*. IEEE Transactions on Information Theory 65(3), 1807–1827, 2019; author manuscript 2016. [Paper](https://arxiv.org/pdf/1608.08622).
