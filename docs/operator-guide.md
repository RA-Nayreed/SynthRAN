# Operator guide

This guide is the shortest supported path from a verified Linux controller to a reproducible SynthRAN experiment. Architecture and research interpretation live elsewhere; this file focuses on what an operator actually runs.

Current evidence: [`results.md`](results.md)  
Experiment protocol: [`experiment.md`](experiment.md)

## Execution boundary

SynthRAN has two user-facing paths:

```text
synthran                 interactive prompt_toolkit workbench
synthran <arguments>     scriptable CLI
```

The interactive workbench currently performs state inspection and state-sensitive operation planning. Provider-facing terminal plans can still report:

```text
Execution: not started
```

That is not a live reservation/deployment/run. The explicit scripted CLI remains the current production path for live provider execution.

## 1. Prepare the controller

Use the SLICES Linux controller or another reviewed Linux host with the supported environment:

```bash
cd ~/SynthRAN
conda activate synthran
python -c "import os; assert os.environ.get('CONDA_DEFAULT_ENV') == 'synthran'"
python -m synthran deps sync
python -m unittest discover -s tests -v
```

The operator establishes SLICES identity and project context outside SynthRAN:

```bash
slices auth show
slices project show
```

If a provider experiment is required for the current provider workflow, create/select it explicitly outside SynthRAN. SynthRAN does not silently log in, switch projects, or create provider experiments.

## 2. Prepare resources

Preview first:

```bash
python -m synthran network prepare \
  --dry-run \
  --owner "$USER" \
  --run-id NETWORK_RUN_ID
```

Then execute only when the reviewed plan is correct:

```bash
python -m synthran network prepare \
  --owner "$USER" \
  --run-id NETWORK_RUN_ID
```

After a successful preparation:

```bash
source .synthran/preparations/NETWORK_RUN_ID/authority.env
INVENTORY=.synthran/preparations/NETWORK_RUN_ID/hosts.ini
```

`authority.env` contains provider identifiers. Keep it private and untracked.

The supported virtual pair places Open5GS/core work and srsRAN/RAN work on distinct prepared nodes. Preparation may reserve/allocate/image the reviewed nodes and build prerequisites, but it stops before Open5GS/srsRAN deployment.

## 3. Run live preflight

```bash
python -m synthran doctor \
  --inventory "$INVENTORY" \
  --evidence-out .synthran/preflight.json
```

A preflight timeout is a controller/provider-readiness problem, not proof that the 5G path itself failed.

## 4. Deploy the base network

```bash
python -m synthran network deploy \
  --inventory "$INVENTORY" \
  --preflight-evidence .synthran/preflight.json \
  --run-id NETWORK_RUN_ID
```

Successful deployment ends at `deployed-unverified`. That state is not yet path proof.

## 5. Prove the 5G path

```bash
python -m synthran network verify \
  --inventory "$INVENTORY" \
  --run-id NETWORK_RUN_ID \
  --timeout 120
```

Only full verification marks the network `path-proven`. The verifier checks the run-owned gNB, srsUE, selected UPF, cell state, `tun_srsue1`, live PDU/route, and UPF `ogstun` path.

Do not reuse an old PDU address as current truth; RFSIM reconciliation can hand off a new PDU.

## 6. Run the deterministic IoT path

```bash
synthran experiment plan \
  --network-run-id NETWORK_RUN_ID \
  --run-id IOT_RUN_ID

synthran experiment run \
  --inventory "$INVENTORY" \
  --network-run-id NETWORK_RUN_ID \
  --run-id IOT_RUN_ID

synthran experiment verify --run-id IOT_RUN_ID
```

An experiment failure does not automatically require base-network redeployment. Preserve its evidence, recover only exact SynthRAN-owned resources, and reverify the base path.

## 7. Choose the external research peer

Capacity calibration and background load must terminate outside the core host. In the reviewed two-node virtual topology the prepared RAN node is the external peer.

Inspect it:

```bash
ansible -i "$INVENTORY" ran_node -m shell -a '
hostname
ip -4 -o addr show
ip -4 route show default
'
```

Set the provider-facing IPv4 address:

```bash
MEASUREMENT_PEER_IP=<prepared-ran-node-provider-ip>
```

Do **not** substitute the core-node address or a Post5G Kubernetes LoadBalancer address.

## 8. Calibrate the UE path

```bash
python -m synthran experiment research calibrate \
  --inventory "$INVENTORY" \
  --network-run-id NETWORK_RUN_ID \
  --target "$MEASUREMENT_PEER_IP" \
  --duration-seconds 10 \
  --out .synthran/research/capacity.json
```

The current accepted campaign used:

```text
network run:        network-acceptance-20260818-09
measurement peer:   172.28.2.95
reference capacity: 66,366,402 bps
calibration:        calibration-20260819-external-08.json
```

That value is evidence for that accepted network epoch. Recalibrate after material network/dependency changes rather than treating it as a universal constant.

## 9. Plan a blocked campaign

Example:

```bash
python -m synthran experiment research campaign-plan \
  --campaign-id CAMPAIGN_ID \
  --network-run-id NETWORK_RUN_ID \
  --seeds 424242,424243,424244 \
  --conditions baseline,load50:0.5,load80:0.8,load95:0.95 \
  --campaign-seed 12345 \
  --out .synthran/campaigns/CAMPAIGN_ID.json
```

Inspect the persisted schedule before execution. Run IDs are immutable and must not be reused after success or failure.

## 10. Execute the campaign

```bash
python -m synthran experiment research campaign-run \
  --campaign .synthran/campaigns/CAMPAIGN_ID.json \
  --inventory "$INVENTORY" \
  --target "$MEASUREMENT_PEER_IP" \
  --reference-capacity-bps REFERENCE_BPS \
  --sensor-period 5 \
  --warmup-seconds 30 \
  --duration-seconds 180 \
  --sample-interval 1 \
  --probe-interval 1 \
  --parallel-flows 2 \
  --run-root /path/to/experiment-results
```

A requested sample interval is a target, not evidence that cadence was achieved. Current sampler hardening causes future runs to fail closed when counter sampling falls materially below the requested rate.

## 11. Analyze only persisted valid runs

```bash
python -m synthran experiment research analyze \
  --campaign .synthran/campaigns/CAMPAIGN_ID.json \
  --run-root /path/to/experiment-results \
  --out .synthran/reports/CAMPAIGN_ID-analysis.json
```

The analyzer filters to runs whose own persisted validity gates are ready, pairs treatments with the baseline from the matching seed block, and computes deterministic bootstrap summaries.

Do not mix older diagnostic campaigns into the treatment dataset just because they are stored under the same results root.

## 12. Read telemetry counts correctly

For v1alpha1 research summaries, the fixed `expected_events` count is nominal `duration / sensor_period` occupancy. Exact window boundaries can contain one fewer periodic record without an internal sequence gap.

Therefore:

- use sequence gaps/duplicates for observed telemetry continuity;
- do not call a contiguous 35-record stream “one lost packet” simply because the nominal count is 36;
- keep the nominal coverage number as a window-occupancy diagnostic.

This distinction is documented with the campaign-06 raw evidence in [`results.md`](results.md).

## 13. Preserve results

Keep raw evidence outside Git. A preservation bundle should contain the raw run tree plus the campaign plan, calibration, dependency lock, code revision, and checksums.

When generating `SHA256SUMS`, exclude the checksum manifest itself.

Publish only small sanitized derivatives (for example campaign analysis JSON and figures) under `results/`.

## Failure and recovery rules

- Never reuse preparation, deployment, experiment, campaign-run, or operation IDs.
- Never infer ownership from a resource name alone.
- Never use broad wildcard or process cleanup when an exact run-owned target is required.
- A measurement failure does not by itself justify redeploying a path-proven base network.
- Preserve partial evidence and diagnose the smallest failing boundary first.
- If clean rollback cannot be proven, fail closed and retain recovery-required state.

## Current accepted result

The current accepted research milestone is `campaign-20260819-06`: 12/12 valid runs over baseline, 50%, 80%, and 95% load. See [`results.md`](results.md) for the actual measurements, limitations, S3 checksums, and next scientific question.
