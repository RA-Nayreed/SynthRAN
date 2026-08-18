# Operator Guide

## Current capability

SynthRAN has two operator-facing interface paths with different current execution boundaries.

### Interactive terminal

Running:

```sh
synthran
```

opens the session-first `prompt_toolkit` terminal. It provides truthful workspace/application status, strict slash-command parsing, OBSERVE/OPERATE mode gating, and state-sensitive immutable operation planning.

Every registered workflow command now reaches application policy, including `/reserve`, `/up`, `/verify`, `/recover`, `/run baseline|congestion`, `/stop`, `/collect`, `/logs ...`, and `/down`.

**The terminal does not yet execute those provider/domain operations.** A successful workflow plan renders `Execution: not started`. Do not interpret that as a reservation, deployment, experiment start/stop, remote collection/log read, or teardown.

The terminal must not call the scripted CLI secretly to cross that boundary.

### Scripted live workflow

The existing explicit CLI remains the current live operator path:

```text
resource preparation
-> read-only live preflight
-> explicit 5G deployment
-> read-only gNB/srsUE/tunnel/UPF proof
-> integrated IoT-to-5G experiment
-> capacity calibration
-> controlled research measurement
-> optional campaign execution and offline analysis
```

Live commands are operator-executed from a verified Linux SLICES controller. The accepted virtual configuration uses Open5GS + srsRAN + one srsUE + RFSIM.

The controlled research **baseline** is live accepted. Campaign scheduling/execution machinery is implemented, but the historical load50 pilot is invalid and does not prove loaded-condition behavior. Fresh valid loaded runs are still required.

## 1. Prepare the controller

Run live commands only from the Linux SLICES Webshell, or an SSH session to its documented management host. Activate the exact `synthran` Conda environment:

```sh
cd ~/SynthRAN
conda activate synthran
python -c "import os; assert os.environ.get('CONDA_DEFAULT_ENV') == 'synthran'"
python -m synthran deps sync
python -m unittest discover -s tests -v
```

The operator establishes SLICES login, project, and provider-experiment context. SynthRAN does not perform these account/context mutations:

```sh
slices auth login
slices auth show
slices project use PROJECT
slices experiment show EXPERIMENT
```

If the provider experiment does not exist, the operator creates it explicitly outside SynthRAN and verifies it again.

Verify the read-only controller boundary:

```sh
python -m synthran slices doctor \
  --slices-project PROJECT \
  --slices-experiment EXPERIMENT
```

Export non-secret context for later explicit CLI commands:

```sh
export SYNTHRAN_SLICES_PROJECT=PROJECT
export SYNTHRAN_SLICES_EXPERIMENT=EXPERIMENT
```

### Persistent terminal workspace

There is currently no top-level scripted `synthran init` command.

When `synthran` is launched with no arguments in an uninitialized checkout, the terminal performs the verified local initialization flow. It can adopt compatible pre-existing `.synthran` experiment evidence without moving or deleting it and can create the durable local SynthRAN requested experiment when the workspace is `EMPTY`.

Initialization and local experiment creation do not reserve/allocate/deploy provider resources and do not create the SLICES provider experiment.

## 2. Preview resource preparation

Choose a unique lowercase run ID and preview:

```sh
python -m synthran network prepare \
  --dry-run \
  --owner OPERATOR \
  --run-id network-001
```

The default reviewed pair uses `sopnode-f2` for core and `sopnode-f3` for RAN. Core and RAN must be different nodes. The adapter also knows other reviewed locked upstream mappings.

Dry-run does not contact POS or mutate provider resources.

## 3. Live resource preparation

Run only from the verified Linux controller:

```sh
python -m synthran network prepare \
  --owner OPERATOR \
  --run-id network-001
```

The guarded preparation path can:

- validate the lock, selected nodes, tools, run ID, and locked checkout;
- create an isolated detached worktree and apply the commit-bound preparation patch;
- install exact required Ansible collections and syntax-check playbooks before POS mutation;
- reject foreign, partial, or split allocations;
- create or verify one current reservation;
- allocate the reviewed node pair together and verify shared allocation ownership;
- image/reset nodes and build the reviewed Kubernetes foundation;
- install required pinned direct tooling;
- stop before Open5GS/srsRAN deployment.

It never calls upstream interactive `deploy.sh`, never guesses ownership, and never performs broad rollback of partially modified provider state.

After successful preparation:

```sh
source .synthran/preparations/network-001/authority.env
INVENTORY=.synthran/preparations/network-001/hosts.ini
```

The ignored authority file contains sensitive provider identifiers with restricted permissions. Do not print, copy, or commit it.

## 4. Run read-only live preflight

```sh
python -m synthran doctor \
  --inventory "$INVENTORY" \
  --evidence-out .synthran/preflight.json
```

The live doctor verifies current controller/provider authority, strict SSH/tool state, Kubernetes prerequisites, and locked inputs. READY evidence is bound to the exact reviewed inputs and has a limited freshness window.

A timeout or controller-context failure is not proof of a radio/network-path failure; keep controller readiness and path proof distinct.

## 5. Explicitly deploy the 5G network

```sh
python -m synthran network deploy \
  --inventory "$INVENTORY" \
  --preflight-evidence .synthran/preflight.json \
  --run-id network-001
```

Deployment uses the locked `5g_ansible` checkout plus narrow SynthRAN overlays, pinned transitive source commits, and selected digest-pinned images. It never reserves, allocates, images, or resets nodes.

Successful deployment ends at:

```text
deployed-unverified
```

That is not path proof.

## 6. Prove the base 5G path

```sh
python -m synthran network verify \
  --inventory "$INVENTORY" \
  --run-id network-001 \
  --timeout 120
```

The verifier requires exactly one run-owned Ready gNB, srsUE, and selected UPF; verifies pinned runtime identity; proves gNB cell activation; validates `tun_srsue1`, its current PDU/route; and verifies the UPF `ogstun` path.

Only full success marks the network manifest `path-proven`.

The accepted reference base network is `network-acceptance-20260817-04` (`PATH PROVEN`).

## 7. Run the deterministic IoT-to-5G experiment

Preview the scenario without live mutation:

```sh
synthran experiment plan \
  --network-run-id network-001 \
  --run-id exp-001
```

Execute explicitly:

```sh
synthran experiment run \
  --inventory "$INVENTORY" \
  --network-run-id network-001 \
  --run-id exp-001
```

Important runtime safety properties:

- the base network must already be path-proven;
- stale/orphan recovery targets only provably SynthRAN-owned process signatures;
- reserved remote ports are checked before mutation;
- privileged `tunslip6/tun0` creation is isolated to the root core node;
- the live UE PDU is rediscovered after srsUE/RFSIM reconciliation rather than assumed from old evidence;
- the edge broker route is explicit through `tun_srsue1`;
- cleanup removes exact run-scoped resources and then reproves the base network;
- failed runs retain their evidence and run IDs are never reused.

Read persisted acceptance evidence without live mutation:

```sh
synthran experiment verify --run-id exp-001
```

The accepted reference IoT run is `iot-acceptance-20260817-06` (`IOT-TO-5G PATH PROVEN`).

See `docs/experiment.md` for topology, artifacts, and acceptance criteria.

## 8. Calibrate reference UE-path capacity

Before fractional-load research runs:

```sh
python -m synthran experiment research calibrate \
  --inventory "$INVENTORY" \
  --network-run-id network-001 \
  --target CORE_IP \
  --duration-seconds 10 \
  --out .synthran/research/capacity-network-001.json
```

The command verifies the accepted network, discovers live UE state, manages the temporary target route and run-owned iperf3 server, measures saturating UDP goodput, and cleans its temporary artifacts.

Accepted reference calibration: `calibration-20260817-02.json`, recording `67,253,028 bps`.

## 9. Plan and execute controlled research measurements

Render one immutable research specification:

```sh
python -m synthran experiment research plan \
  --campaign-id pilot-01 \
  --network-run-id network-001 \
  --run-id pilot-01-baseline \
  --condition baseline \
  --sensor-period 5 \
  --warmup-seconds 30 \
  --duration-seconds 180
```

Execute the baseline:

```sh
python -m synthran experiment research run \
  --inventory "$INVENTORY" \
  --campaign-id pilot-01 \
  --network-run-id network-001 \
  --run-id pilot-01-baseline \
  --condition baseline \
  --probe-target CORE_IP \
  --sensor-period 5 \
  --warmup-seconds 30 \
  --duration-seconds 180
```

For loaded runs, configure the target rate from a fixed reference capacity using `--target-fraction` or `--target-bps` as required by the research specification.

The current research runtime includes validity gates for:

- current base-path proof before measurement;
- current path reproof after warmup and after measurement;
- exact run-owned UE/PDU/route handoff;
- bounded RTT probe behavior including all-timeout records;
- owned iperf3 server/control readiness;
- load-client establishment and load-target validity;
- synchronized network sampling and transport-path completeness;
- telemetry sequence integrity;
- cleanup and base-network reproof.

Zero telemetry is not automatically interpreted as a network scientific result; independent path/load/instrumentation validity must remain healthy.

The accepted reference baseline is `pilot-20260817-03-baseline`, which is ready for campaign analysis.

### Invalid historical load50 run

`pilot-20260817-03-load50` is diagnostic evidence only.

It must **not** be interpreted as proof that 50% load caused telemetry failure or congestion because:

- the iperf3 client did not establish its control connection;
- the requested background UDP load was not established;
- telemetry was absent and RTT probes failed;
- local/ingress counters moved while the UPF path did not;
- the underlying RFSIM/5G transport collapsed before a valid measurement condition existed.

A fresh valid load50 run is required before load50 can enter campaign analysis. The same validity standard applies to later load80/load95 runs.

## 10. Multi-run campaign and offline analysis

Plan a deterministic blocked campaign:

```sh
python -m synthran experiment research campaign-plan \
  --campaign-id campaign-01 \
  --network-run-id network-001 \
  --seeds 424242,424243,424244 \
  --conditions baseline,load50:0.5,load80:0.8,load95:0.95 \
  --campaign-seed 12345 \
  --out .synthran/campaigns/campaign-01.json
```

Execute it explicitly only when each condition can satisfy the live validity gates:

```sh
python -m synthran experiment research campaign-run \
  --campaign .synthran/campaigns/campaign-01.json \
  --inventory "$INVENTORY" \
  --target CORE_IP \
  --reference-capacity-bps 67253028 \
  --sensor-period 5 \
  --warmup-seconds 30 \
  --duration-seconds 180
```

Analyze persisted valid runs offline:

```sh
python -m synthran experiment research analyze \
  --campaign .synthran/campaigns/campaign-01.json \
  --out .synthran/reports/campaign-01-analysis.json
```

The analyzer computes paired differences against baseline across seed blocks and bootstrap confidence intervals for the supported research metrics.

Do not include invalid runs as if they were valid treatment observations.

## Interactive workflow planning examples

The terminal can inspect and plan against the durable workspace once initialized:

```text
/status
/inspect resources
/inspect network
/config experiment
/mode operate
/run baseline
```

A successful `/run baseline` request creates an R2 `run-baseline` operation plan only if current application state is `PATH_PROVEN`. It does not invoke `synthran experiment research run` and does not start the live measurement.

Similarly, `/down` can create an R3 plan only when the experiment is stopped and current exact teardown targets with permitted ownership are known. It does not execute provider teardown yet.

See `docs/terminal-shell.md` and `docs/application-controller.md`.

## Failure and recovery

Do not reuse preparation, deployment, experiment, campaign-run, or operation IDs.

Preserve partial manifests/logs after failure. Never broadly delete resources or infer ownership from naming alone.

Network and experiment lifecycles are decoupled. An experiment failure does not by itself require base-network redeployment. When RFSIM state stalls, use the reviewed process-level recovery/reconciliation path and re-run network verification rather than defaulting to destructive redeployment.

If a mutation is under the new operation-control path and clean rollback cannot be proven, retain the mutation claim and enter recovery-required state.

## Safety boundary

- The operator executes live preparation, deployment, verification, experiment/research runs, and infrastructure changes.
- The interactive terminal currently plans provider-facing workflows but does not execute them.
- Resource preparation is explicit and stops before 5G deployment.
- Network deployment is separate from reservation/allocation preparation.
- Experiment execution never silently reserves nodes or deploys the base network.
- Provider experiment creation remains outside SynthRAN.
- Unknown/foreign ownership fails closed.
- Destructive work requires exact target scope; never use broad guessed cleanup.
- Automated agents may author offline code/tests/docs, inspect read-only state, prepare non-mutating plans, and analyze evidence, but require explicit operator authorization for live provider mutation.
- No live SLICES or golden-path success is claimed without evidence from the actual run.
