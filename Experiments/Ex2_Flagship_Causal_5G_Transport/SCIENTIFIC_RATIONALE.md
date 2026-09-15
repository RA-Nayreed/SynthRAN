# Experiment 2: scientific rationale, calibration evidence, and interpretation

Experiment 2 asks whether **the timing of the same decoded Ambient-IoT events changes downstream application delivery under controlled competing traffic**. Its scientific contribution is a bridge between an upstream energy-and-access model and a measured 5G gateway transport path. The motivating hypothesis is that clustered releases can create waiting and deadline failures that a smooth, average-rate workload misses. The supplied calibration log does not yet test that hypothesis: qualification passed, but the load-selection rule could not choose the three confirmation conditions.

This analysis distinguishes the executable revision-2 contract in [experiment.yml](experiment.yml), historical repository summaries, the supplied operator log, and conclusions supported by external research. Revision 2 changes calibration and strengthens provenance and analysis; it does not constitute new physical measurements. The associated PR records validation of the implementation separately.

**Why the question matters.** Ambient IoT devices depend on harvested energy and may lack enough stored energy to communicate. Harvesting can be continuous or incidental, and some devices can still communicate regularly. Consequently, intermittent or correlated traffic is a plausible operating condition, not a universal property of every Ambient IoT deployment. These distinctions follow [3GPP TS 22.369, section 4.2](https://www.etsi.org/deliver/etsi_ts/122300_122399/122369/19.03.00_60/ts_122369v190300p.pdf).

Correlated harvesting already has a research basis. Abad, Gunduz, and Ercetin analyze two harvesting nodes sharing a random-access destination, including the case where both or neither harvest at a given time. Their model establishes correlated energy as a legitimate networking variable; it does not validate SynthRAN's particular capacitor model or prove its traffic distribution matches deployed devices. The potential contribution here is the controlled connection from that mechanism to downstream delivery, rather than the existence of correlated energy itself. [Abad et al., Energy harvesting wireless networks with correlated energy sources](https://arxiv.org/abs/1902.04890)

**What Experiment 1 contributes.** The retained [Experiment-1 results](../Ex1_Energy_Correlation_and_Burst_Formation/RESULTS.md) describe 210 model runs: seven conditions and 30 seeds. At the energy knee, the historical summary reports:

| Historical condition mean | Independent harvesting | Common harvesting |
| --- | ---: | ---: |
| Active fraction | 45.4% | 44.5% |
| Realized power correlation | 0.001 | 0.961 |
| Decoded events per second | 12.628 | 11.294 |
| Fano factor | 0.584 | 13.391 |
| Inter-event-gap coefficient of variation | 0.922 | 6.508 |
| Collision rate | 7.30% | 15.33% |

Those numbers motivate a timing-sensitive transport study: broadly similar activation fractions accompany markedly different decoded traffic structure. They also expose a confound in directly replaying independent versus common harvesting: their event counts differ. Experiment 2 addresses that confound by transforming each retained event set internally. These are historical recorded aggregates, not results independently recomputed during this review; the original raw bundles are excluded from Git. Experiment 1 also records reader-AoI contrast intervals crossing zero. It therefore does not establish reader-freshness degradation, and its upstream evidence cannot substitute for Experiment-2 confirmation.

**The hypotheses and their falsification.** For outcome Y, source seed i, and load level l, define:

```text
NP(i,l) = Y(native,i,l) - Y(periodic,i,l)
NR(i,l) = Y(native,i,l) - mean[Y(gap_r1,i,l), Y(gap_r2,i,l)]
```

Both principal outcomes are smaller-is-better, so positive contrasts mean a native-timing penalty.

- **T1, total timing effect:** Native timing has a delivery-delay or deadline-failure penalty relative to periodic release. This tests the consequence of replacing the observed timing pattern with an evenly spaced schedule.
- **T2, gap-order effect:** Native timing differs from the mean of the two exact-gap permutations. A positive penalty supports sensitivity to temporal arrangement beyond the aggregate gap histogram. T1 alone cannot establish T2.
- **T3, load interaction:** The native penalty changes with competing load. The directional expectation is amplification under stronger competition; the implemented contrasts compare NP and NR at near-minus-below and above-minus-below loads within the same source seed.

The direction remains empirical. A shuffle can accidentally preserve or create clusters, and transport scheduling can change which arm fares better. A narrow interval near zero limits the claimed effect; a wide interval is inconclusive. The present manifest does not set a numerical smallest worthwhile effect, so statistical separation from zero must not be relabeled practical importance or equivalence without an independently justified margin.

**How the experiment isolates timing.** Preparation selects all 30 frozen `knee-common` source seeds from the newest complete local Experiment-1 campaign and retains its identity and source revision. That cohort must not be assumed to reproduce the historical table above: its actual bundles and frozen design are the evidence for the new campaign. The native clock runs at 1x speed. Every seed supplies four arms:

| Arm | Timing operation | What the comparison isolates |
| --- | --- | --- |
| `native` | Original completed-decode availability times | Reference event-release process |
| `periodic` | Evenly spaced measurement releases, retaining endpoints | Combined effect of timing regularization |
| `gap_permutation_r1` | Deterministic permutation of measured gaps | Gap order with exact gap values retained |
| `gap_permutation_r2` | Independently seeded permutation of those gaps | A second matched control realization |

Event identity and order, sensor identity, serialized payload, MQTT topic, event count, source horizon, gateway role, and first/last measurement release stay fixed. Warm-up is declared separately. Permuting gaps changes where fixed events occur in time, including individual sensors' update schedules; it is not a targeted manipulation of only one correlation coefficient.

The permutation logic follows constrained-surrogate methodology: rearrange observed values without replacement to retain their distribution while changing temporal order. Two permutations are useful controls but not a sufficient ensemble for a conventional 5% per-trace surrogate rank test; its minimum one-sided p-value with two controls is 1/3. The scientific replication instead comes from the 30 source seeds. Nor does rejection against these controls prove nonlinear dynamics or identify the upstream energy mechanism uniquely. [Schreiber and Schmitz, Surrogate time series, sections 3.1-3.3](https://arxiv.org/pdf/chao-dyn/9909037)

A small queue illustrates the reason for preserving gaps. Assume five jobs each take 100 ms to serve, and the queue initially is empty:

| Schedule | Arrival times, ms | Gaps, ms | Maximum waiting time |
| --- | --- | --- | ---: |
| Clustered | 0, 0, 0, 300, 600 | 0, 0, 300, 300 | 200 ms |
| Rearranged | 0, 0, 300, 300, 600 | 0, 300, 0, 300 | 100 ms |

Count, endpoints, average rate, and gap histogram match exactly. The order alone changes accumulated work. For an ideal single server this is expressed by `W(next) = max(0, W(current) + service_time - next_gap)`. This is an explanatory calculation, not a model fitted to the 5G testbed or a prediction of its effect size.

**The confirmation matrix and execution.** The frozen design is 30 source seeds x four timing arms x three calibrated loads = **360 replays**. The three ten-seed sessions organize execution and drift checks; they do not increase independent sample size. Arm order is deterministically randomized within each source/load block, and drift sentinels run every 12 replays. Complete matched blocks reduce the risk that reservation expiry systematically separates treatment arms.

The experiment consumes the deployment already accepted by `deploy.sh`. One verified UE carries the workload and another carries paced UDP competition to an N6-side sink. Core, RAN, radio, nodes, slices, UE roles, and deployment identity are retained as provenance. A deployment change starts a different campaign. Shared bottlenecks and slice/scheduler behavior still require actual deployment evidence: merely using two UEs does not prove both flows compete equally at the radio scheduler. The downstream gateway topology is scientifically relevant to indirect Ambient-IoT communication, which TS 22.369 describes as involving an assisting UE; this replay does not implement or certify that complete standardized mode. [3GPP TS 22.369, section 4.4](https://www.etsi.org/deliver/etsi_ts/122300_122399/122369/19.03.00_60/ts_122369v190300p.pdf)

**What the outcomes mean.** The principal delay is application receipt time minus scheduled release time. It includes publisher lateness, client queuing, transport, broker processing, and subscriber delivery. Recording publisher release error separately helps distinguish scheduling trouble from later delivery delay. The p95 is conditional on receipts observed by the declared drain; absent receipts do not acquire zero delay. The complementary 0.5-second deadline-failure fraction includes expected events that arrive late or remain missing, preventing selective delivery from concealing overload.

MQTT uses an ordered, lossless transport such as TCP. Its QoS-1 PUBACK acknowledges a delivery exchange with the broker; it does not establish that the receiving application callback has occurred. UDP competitor loss, TCP packet recovery, MQTT protocol acknowledgment, and application deadline failure therefore are different measurements. [OASIS MQTT 3.1.1, sections 4.2-4.3](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html)

Age of Information measures time since generation of the freshest received status, rather than simply transit time. Long intervals without new information can increase age even when every delivery is fast. This makes AoI valuable but distinct from the principal timing question. [Yates and Kaul, The Age of Information: Real-Time Status Updating by Multiple Sources](https://arxiv.org/pdf/1608.08622) SynthRAN retains generation timestamps; a surrogate release may precede its modeled generation, making physical generation-based AoI invalid for that transformed arm. Respect the transformation's `generation_age_valid` contract instead of interpreting such ages causally.

The 0.5-second deadline and secondary 2-second age threshold are study choices. They do not establish Ambient IoT standards compliance. TS 22.369 specifies application-dependent requirements, including 1-second tracking latency and 20-30-second room-environment monitoring latency. Those examples concern different service boundaries and use cases. [3GPP TS 22.369, tables 6.3-1 and 6.4-1](https://www.etsi.org/deliver/etsi_ts/122300_122399/122369/19.03.00_60/ts_122369v190300p.pdf)

**What the supplied stop actually establishes.** The operator log reports three ten-second calibration repeats at each requested rate. Their medians are:

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

The original rule chooses ABOVE as the first ascending rate with median delivery strictly below 0.98, NEAR as its predecessor, and BELOW as the preceding point. None crossed. Qualification passed, calibration could not select levels, and freeze/360-run confirmation/analysis had not started in this supplied run. Approximately 99.77% delivery at requested 50 Mbps establishes only that the sampled loss threshold was not crossed. The pasted output lacks achieved sender rates and delay measurements. It cannot establish true 50-Mbps path capacity, absence of queueing, or any T1-T3 result.

Calling this a physical "congestion knee" is too strong. Tail-drop loss occurs when a queue becomes full; waiting can grow before overflow, and packet bursts can delay other traffic. [RFC 7567, section 2](https://www.rfc-editor.org/rfc/rfc7567.html#section-2) Network-characterization guidance includes delay and jitter, and explicitly limits the transferability of its own loss-based congestion definitions. [RFC 7928, sections 2.6 and 8.2.1](https://www.rfc-editor.org/rfc/rfc7928.html) Here BELOW/NEAR/ABOVE are operational labels around an end-to-end UDP loss boundary, not measured positions around a radio-capacity limit.

**Why revision 2 is justified.** The revision retains the original 0.98 threshold and extends the prespecified ascending grid to `[5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120, 150, 200, 250]` Mbps. Retaining the low-rate points preserves the predecessor rule. Every repeat must achieve 95-105% of its requested application-payload rate without sender errors. A request for 200 Mbps delivered by a 90-Mbps generator cannot become evidence about a 200-Mbps offered condition.

UDP itself has no congestion control, making a paced application useful for prescribing offered competition but unlike an adaptive TCP competitor. Achieved generation and received delivery must be recorded separately. [RFC 8085, sections 1 and 3.1](https://www.rfc-editor.org/rfc/rfc8085.html) The tolerance is an engineering validity rule, not a standardized accuracy guarantee or proof that pacing has no microbursts.

Revision 2 retains every probe before stopping, including invalid repeats and failed or unbracketed sweeps, fixing the previous loss of the complete calibration result when selection raised an error. It stops the ascending sweep after the first crossing has three valid repeats; higher points are unnecessary for the declared selector. If valid predecessors cannot be selected, confirmation remains blocked. This is a prospective revision after a calibration pilot, so it requires a new campaign rather than silently replacing the stopped campaign's rules.

The full study contract is frozen with the source cohort, deployment, loads, sessions, measurements, and statistical settings. Analysis uses the frozen design, with contrast-specific exclusions and paired load interactions added in this revision. An invalid permutation arm must not discard a valid native-periodic comparison. For each estimable outcome and contrast, report included seeds and exclusion reasons; infrastructure invalidity is different from genuine overloaded delivery failure.

Paired bootstrap intervals use source seeds, averaging permutation outcomes within source/load before resampling. Interactions use the same eligible seeds across both loads. Thirty seeds is the available cohort size, not a demonstrated power calculation. A prospective precision or power study needs a justified practical effect and plausible between-seed variability; these remain unresolved. The declared intervals are pointwise 95% intervals without multiplicity adjustment; they cannot be advertised as a familywise-confirmed result across all outcomes, loads, and contrasts.

The bootstrap assumes independent source-seed differences and does not model shared session drift or propagate clock uncertainty. Controller-bracketed clock probes bound offsets at their measurement times; extending those bounds through a replay assumes stable clocks. Sentinels help detect some drift, but do not establish continuous stationarity. Exclusion patterns, limited source diversity, and uncertainty in each run's p95 remain relevant even when implementation tests pass.

**What a completed study could support.** A positive NP establishes a conditional replay-timing penalty; a positive NR additionally implicates gap arrangement beyond its histogram. Positive paired load interactions support amplification over the calibrated range. These conclusions remain conditional on the modeled decoded cohort and accepted transport deployment. Physical harvesting, Ambient-IoT RF propagation, access collisions, and decoding are upstream of replay and are not experimentally manipulated here.

To attribute an observed penalty specifically to radio queueing, retain aligned sender-rate and pacing evidence, workload/competitor overlap, queue or scheduler counters, retransmissions, and endpoint CPU/socket-drop evidence where available. These are diagnostic needs, not claims that all such telemetry is already implemented. End-to-end outcomes alone cannot locate the bottleneck.

Future studies could calibrate with queue/delay telemetry, test adaptive competing traffic, vary shared versus isolated slices, use more surrogate draws, and validate source timing against measured harvesting traces. Such extensions should be declared prospectively. The present repair enables an auditable test of the stated hypotheses; it neither supplies the missing confirmation measurements nor guarantees they will favor native-timing penalties.

**References.** External sources were checked on 14-15 September 2026; repository history and the supplied calibration transcript provide the project-specific evidence.

1. 3GPP/ETSI. *Service requirements for Ambient power-enabled IoT*. TS 22.369 / ETSI TS 122 369 V19.3.0, Release 19, January 2026. [Specification](https://www.etsi.org/deliver/etsi_ts/122300_122399/122369/19.03.00_60/ts_122369v190300p.pdf).
2. M. Salehi Heydar Abad, D. Gunduz, and O. Ercetin. *Energy harvesting wireless networks with correlated energy sources*. IEEE WCNC 2016; author manuscript deposited 2019. [Paper](https://arxiv.org/abs/1902.04890).
3. T. Schreiber and A. Schmitz. *Surrogate time series*. Physica D 142, 346-382, 2000; author manuscript 1999. [Paper](https://arxiv.org/pdf/chao-dyn/9909037).
4. F. Baker and G. Fairhurst. *IETF Recommendations Regarding Active Queue Management*. RFC 7567, July 2015. [RFC](https://www.rfc-editor.org/rfc/rfc7567.html).
5. N. Kuhn et al. *Characterization Guidelines for Active Queue Management (AQM)*. RFC 7928, July 2016. [RFC](https://www.rfc-editor.org/rfc/rfc7928.html).
6. L. Eggert, G. Fairhurst, and G. Shepherd. *UDP Usage Guidelines*. RFC 8085, March 2017. [RFC](https://www.rfc-editor.org/rfc/rfc8085.html).
7. A. Banks and R. Gupta, editors. *MQTT Version 3.1.1*. OASIS Standard, 29 October 2014. [Specification](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html).
8. R. D. Yates and S. K. Kaul. *The Age of Information: Real-Time Status Updating by Multiple Sources*. IEEE Transactions on Information Theory 65(3), 1807-1827, 2019; author manuscript 2016. [Paper](https://arxiv.org/pdf/1608.08622).
