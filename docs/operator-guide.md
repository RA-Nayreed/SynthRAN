# Operator guide

This is the complete supported path from a new SLICES user context to a reproducible SynthRAN research campaign. It documents the provider objects SynthRAN expects, what SynthRAN creates itself, the order of live operations, and where the resulting evidence belongs.

Current evidence: [`results.md`](results.md)  
Experiment protocol: [`experiment.md`](experiment.md)  
Architecture: [`architecture.md`](architecture.md)

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

That is not a live reservation, deployment, or experiment run. The explicit scripted CLI remains the current production path for live provider execution.

## 1. SLICES account and project

A SLICES **project is required**. Resources belong to experiments, and experiments belong to a project.

SynthRAN does **not** create or approve SLICES projects. Use the [SLICES portal](https://portal.slices-ri.eu/) to request a new project or join an existing one. For the Post5G beta service, `post5g-beta` is the common example project; access to it is granted through the SLICES/Post5G onboarding flow.

After membership is approved:

```bash
slices auth login
slices project list
slices project use PROJECT_NAME
slices auth show
slices project show
```

`project use` changes the active SLICES CLI project. SynthRAN never changes it silently.

## 2. Create the SLICES provider experiment

The current live SynthRAN path requires an existing provider experiment. Create it explicitly in the selected project:

```bash
export PROJECT_NAME=PROJECT_NAME
export PROVIDER_EXPERIMENT=EXPERIMENT_NAME

slices project use "$PROJECT_NAME"
slices experiment create "$PROVIDER_EXPERIMENT" --duration 4h
slices experiment show "$PROVIDER_EXPERIMENT"
```

Choose a duration that covers preparation, deployment, calibration, the campaign, and cleanup. The provider experiment is not the same object as a SynthRAN research campaign: it is the SLICES control-plane container under which provider resources and the Post5G network identity live.

Do not reuse an expired/deleted provider experiment name as if it were still current authority. Create a fresh provider experiment when the old one no longer exists.

## 3. Allocate the Post5G network prefix

The current controller verification requires an active Post5G network identity for the provider experiment. Acquire it before SynthRAN resource preparation:

```bash
post5g experiment prefix "$PROVIDER_EXPERIMENT"
```

The provider returns a network prefix, load-balancer address, and expiration. SynthRAN's controller doctor re-reads this state and rejects missing, malformed, mismatched, or expired network identity.

Export the context once:

```bash
export SYNTHRAN_SLICES_PROJECT="$PROJECT_NAME"
export SYNTHRAN_SLICES_EXPERIMENT="$PROVIDER_EXPERIMENT"
```

Keep the prefix allocated while the live experiment still depends on it. Release it only after the campaign/evidence work is complete:

```bash
post5g experiment prefix "$PROVIDER_EXPERIMENT" --release
```

## 4. Prepare the SynthRAN controller

Use the reviewed SLICES Linux controller or another supported Linux host with the SLICES, Post5G, POS, SSH, Git, and Ansible commands available.

```bash
cd ~/SynthRAN
conda activate synthran
python -c "import os; assert os.environ.get('CONDA_DEFAULT_ENV') == 'synthran'"
python -m synthran deps sync
python -m unittest discover -s tests -v
```

Then verify the provider context read-only:

```bash
python -m synthran slices doctor
```

This checks the selected project, exact existing SLICES experiment, active Post5G prefix, locked controller dependencies, and required provider tools. A failure here is a controller/provider-context problem; do not start mutations until it is resolved.

## 5. Reserve, allocate, image, and prepare resources

For the accepted virtual topology, SynthRAN uses two distinct reviewed nodes: one for the Open5GS/core side and one for the srsRAN/RAN side.

Set the SLICES/POS owner identity and a unique preparation ID:

```bash
export SYNTHRAN_OWNER=YOUR_SLICES_USERNAME
export PREPARATION_RUN=prepare-001
```

Preview first:

```bash
python -m synthran network prepare \
  --dry-run \
  --owner "$SYNTHRAN_OWNER" \
  --duration-minutes 120 \
  --run-id "$PREPARATION_RUN"
```

Then execute the reviewed plan:

```bash
python -m synthran network prepare \
  --owner "$SYNTHRAN_OWNER" \
  --duration-minutes 120 \
  --run-id "$PREPARATION_RUN"
```

Without `--reservation-id`, this command may create the required POS reservation, acquire the reviewed node pair, image it, and install preparation prerequisites. If you already have an active reservation that you intentionally want to reuse, pass its exact identifier with `--reservation-id`.

After success:

```bash
source ".synthran/preparations/$PREPARATION_RUN/authority.env"
export INVENTORY=".synthran/preparations/$PREPARATION_RUN/hosts.ini"
```

`authority.env` contains live provider identifiers such as reservation/allocation authority. Keep it private and untracked.

## 6. Run the live preflight

```bash
python -m synthran doctor \
  --inventory "$INVENTORY" \
  --evidence-out .synthran/preflight.json
```

The live doctor binds current project/experiment, reservation/allocation ownership, inventory, locked dependencies, SSH reachability, and deployment prerequisites into fresh sanitized readiness evidence.

A timeout or provider mismatch is not proof that the 5G path itself failed. Fix the failed boundary rather than redeploying unrelated healthy state.

## 7. Deploy the base 5G network

Use a new immutable network run ID:

```bash
export NETWORK_RUN=network-001

python -m synthran network deploy \
  --inventory "$INVENTORY" \
  --preflight-evidence .synthran/preflight.json \
  --run-id "$NETWORK_RUN"
```

Successful deployment ends at `deployed-unverified`. That is intentionally weaker than path proof.

## 8. Prove the live 5G path

```bash
python -m synthran network verify \
  --inventory "$INVENTORY" \
  --run-id "$NETWORK_RUN" \
  --timeout 120
```

Only full verification marks the network `path-proven`. The verifier checks the exact run-owned gNB, srsUE, selected UPF, cell state, `tun_srsue1`, current PDU/route, and UPF `ogstun` path.

Do not copy an old PDU address into a new experiment. RFSIM reconciliation can attach the UE with a new live PDU; current observation wins over historical evidence.

## 9. Optional deterministic IoT-only acceptance

Before a controlled load campaign, the deterministic IoT path can be exercised by itself:

```bash
export IOT_RUN=iot-001

synthran experiment plan \
  --network-run-id "$NETWORK_RUN" \
  --run-id "$IOT_RUN"

synthran experiment run \
  --inventory "$INVENTORY" \
  --network-run-id "$NETWORK_RUN" \
  --run-id "$IOT_RUN"

synthran experiment verify --run-id "$IOT_RUN"
```

An experiment failure does not automatically justify base-network redeployment. Preserve its evidence, recover only exact SynthRAN-owned resources, and reverify the base path.

## 10. Choose the external research peer

Capacity calibration and controlled background load must terminate outside the 5G core host. In the reviewed two-node virtual topology the prepared RAN node is the external peer.

Inspect the RAN node addresses:

```bash
ansible -i "$INVENTORY" ran_node -m shell -a '
hostname
ip -4 -o addr show
ip -4 route show default
'
```

Set its provider-facing IPv4 address:

```bash
export MEASUREMENT_PEER_IP=PEER_IPV4
```

Do **not** substitute the core-node address or a Post5G Kubernetes LoadBalancer address. A same-host target can collapse into a Kubernetes/hairpin path and invalidate the intended external user-plane capacity measurement.

## 11. Calibrate the UE path

Use a fresh calibration whenever the network/dependency epoch materially changes:

```bash
export CALIBRATION=.synthran/research/capacity.json

python -m synthran experiment research calibrate \
  --inventory "$INVENTORY" \
  --network-run-id "$NETWORK_RUN" \
  --target "$MEASUREMENT_PEER_IP" \
  --duration-seconds 10 \
  --out "$CALIBRATION"

export REFERENCE_BPS=$(jq -r '.reference_capacity_bps' "$CALIBRATION")
```

The accepted campaign-06 calibration measured `66,366,402 bps`. That value belongs to that accepted network epoch; it is not a universal physical-radio capacity claim.

## 12. Plan a randomized blocked campaign

Use unique campaign and run identities. A failed or successful run ID is never reused.

```bash
export CAMPAIGN_ID=campaign-001
export CAMPAIGN_FILE=".synthran/campaigns/$CAMPAIGN_ID.json"

python -m synthran experiment research campaign-plan \
  --campaign-id "$CAMPAIGN_ID" \
  --network-run-id "$NETWORK_RUN" \
  --seeds 424242,424243,424244 \
  --conditions baseline,load50:0.5,load80:0.8,load95:0.95 \
  --campaign-seed 12345 \
  --out "$CAMPAIGN_FILE"
```

Inspect the persisted schedule before execution. Each seed is one block; every condition occurs once per block in reproducibly randomized order.

## 13. Execute the controlled campaign

Choose a results root with enough space and preserve it after the campaign:

```bash
export RUN_ROOT=.synthran/experiments

python -m synthran experiment research campaign-run \
  --campaign "$CAMPAIGN_FILE" \
  --inventory "$INVENTORY" \
  --target "$MEASUREMENT_PEER_IP" \
  --reference-capacity-bps "$REFERENCE_BPS" \
  --sensor-period 5 \
  --warmup-seconds 30 \
  --duration-seconds 180 \
  --sample-interval 1 \
  --probe-interval 1 \
  --parallel-flows 2 \
  --load-port 5220 \
  --run-root "$RUN_ROOT"
```

A requested sample interval is a target, not proof of achieved cadence. The current sampler collects independent ingress/UE/UPF reads concurrently and rejects a run when achieved sample count falls materially below the requested cadence.

For loaded conditions, successful iperf output alone is insufficient. The run also requires current path identity, an established run-owned control connection before the window, target-rate achievement, instrumentation evidence, post-window path proof, and successful cleanup/base-network reproof.

## 14. Analyze only persisted valid runs

```bash
mkdir -p .synthran/reports
export ANALYSIS=".synthran/reports/$CAMPAIGN_ID-analysis.json"

python -m synthran experiment research analyze \
  --campaign "$CAMPAIGN_FILE" \
  --run-root "$RUN_ROOT" \
  --out "$ANALYSIS"
```

The analyzer reads only persisted runs whose validity gates report readiness, then pairs loaded treatments with the baseline from the matching seed block.

Do not mix older diagnostic runs into a treatment dataset merely because they live under the same storage root.

## 15. Interpret telemetry counts correctly

For v1alpha1 summaries, `expected_events = duration / sensor_period` is a nominal fixed-window occupancy target. A periodic source can place one fewer record inside an exact measurement boundary even with a perfectly contiguous sequence.

Therefore:

- use sequence gaps/duplicates for observed telemetry continuity;
- do not call a contiguous 35-record stream “one lost packet” solely because the nominal count is 36;
- keep `delivery_ratio` as a window-occupancy diagnostic rather than a packet-loss estimator.

Campaign-06 contains zero observed sequence gaps and zero duplicates. The evidence is documented in [`results.md`](results.md).

## 16. Preserve the raw evidence

The complete raw campaign should be preserved outside normal Git history as an immutable bundle. Include:

```text
raw run tree
campaign plan
capacity calibration
exact dependency lock
code revision
terminal/campaign log
provenance metadata
per-file SHA-256 manifest
```

When building `SHA256SUMS`, exclude `SHA256SUMS` itself.

For SLICES object storage, the repository does not store S3 credentials. Configure the MinIO client (`mc`) with your own SLICES object-storage access key, then upload under a project-scoped path such as:

```text
s3://PROJECT_BUCKET/synthran/campaigns/YYYY-MM-DD/CAMPAIGN_ID/
```

Always compute an archive SHA-256 locally and recompute it from the remote object before declaring preservation successful. Keep the checksum beside the archive and retain object version/replication metadata when available.

The accepted campaign-06 bundle is preserved this way and its archive-level checksum was verified byte-for-byte. See [`results.md`](results.md) for the exact object path and checksum.

The **unrounded campaign analysis JSON remains tracked under [`results/`](../results/)** for direct GitHub inspection. Do not replace it with rounded values merely to satisfy the privacy scanner; the scanner understands numeric JSON measurements separately from subscriber identifiers.

## 17. Finish provider use cleanly

Only after the raw evidence is preserved and the live provider network identity is no longer required:

```bash
post5g experiment prefix "$PROVIDER_EXPERIMENT" --release
```

The SLICES provider experiment itself expires according to its configured duration. Do not delete or release provider state early while an active reservation/campaign still depends on it.

## Failure and recovery rules

- Never reuse preparation, deployment, experiment, campaign-run, or operation IDs.
- Never infer ownership from a resource name alone.
- Never use broad wildcard/process cleanup when an exact run-owned target is required.
- A measurement failure does not by itself justify redeploying a path-proven base network.
- Preserve partial evidence and diagnose the smallest failing boundary first.
- If clean rollback cannot be proven, fail closed and retain recovery-required state.
- Do not release the Post5G prefix until the provider network identity is genuinely no longer needed.

## Current accepted result

`campaign-20260819-06` is the current accepted controlled research campaign: 12/12 valid runs over baseline, 50%, 80%, and 95% load. See [`results.md`](results.md) for measured values, raw-analysis location, S3 checksums, known limitations, and the next scientific question.
