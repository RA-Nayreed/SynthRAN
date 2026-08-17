# Operator Guide

## Current capability

SynthRAN provides an offline-tested guarded network and experiment lifecycle:

```text
resource preparation
-> read-only live preflight
-> explicit 5G deployment
-> read-only gNB/srsUE/tunnel/UPF proof
-> integrated IoT-to-5G experiment
```

Every live step is operator-executed from a verified SLICES shell. The lean preparation implementation can create a reservation, jointly allocate two nodes, image and reset them, build Kubernetes, and install version-pinned remote tools. The operator accepted that upstream bootstrap transitives are not artifact-locked, so the guarded live preparation path is enabled.

The supported pair defaults to `sopnode-f2` for the core and `sopnode-f3` for the RAN. The adapter also knows the locked upstream mappings for `sopnode-f1` and `sopnode-w3`. Core and RAN must be different nodes.

Run live commands only from the Linux SLICES Webshell, or an SSH session to that documented management host. The exact locked `synthran` Conda environment must be active. Local and CI environments support only offline validation and dry-run planning.

## 1. Prepare the controller

```sh
cd ~/SynthRAN
conda activate synthran
python -c "import os; assert os.environ.get('CONDA_DEFAULT_ENV') == 'synthran'"
python -m synthran deps sync
python -m unittest discover -s tests -v
```

The operator establishes the SLICES session and context. These are intentionally not automated by SynthRAN:

```sh
slices auth login
slices auth show
slices project use PROJECT
slices project show
slices experiment show EXPERIMENT
```

If the experiment does not exist, the operator may create it explicitly with `slices experiment create EXPERIMENT`, then inspect it again. SynthRAN never logs in, changes projects, or creates experiments.

Verify the complete read-only controller boundary:

```sh
python -m synthran slices doctor \
  --slices-project PROJECT \
  --slices-experiment EXPERIMENT
```

This check requires Linux, the active `synthran` environment, the exact locked Python and Ansible versions, POS 2.5.35, SLICES authentication, the selected project, and the existing experiment. Each read-only controller probe allows 60 seconds because project lookup can be slower than local version checks. Export the non-secret context for later commands:

```sh
export SYNTHRAN_SLICES_PROJECT=PROJECT
export SYNTHRAN_SLICES_EXPERIMENT=EXPERIMENT
```

## 2. Preview resource preparation

Choose a unique lowercase run ID:

```sh
python -m synthran network prepare \
  --dry-run \
  --owner OPERATOR \
  --run-id network-001
```

The default plan creates a 120-minute reservation for `sopnode-f2` and `sopnode-f3`. To reuse an active reservation, add `--reservation-id NUMERIC_ID`. To select another reviewed pair, add `--core-node NODE --ran-node NODE`.

Dry-run writes nothing and does not contact POS.

## 3. Live preparation

`dependencies.lock.yml` records `resource_bootstrap.status` as `ready` after explicit operator acceptance. Run the modifying command only from the verified Linux SLICES controller; it may reserve, allocate, image, and reset the selected nodes:

```sh
python -m synthran network prepare \
  --owner OPERATOR \
  --run-id network-001
```

The implementation is intentionally smaller than an air-gapped or artifact-complete bootstrap. It accepts upstream apt, chart, manifest, and installer transitives for the first native experiment. Do not represent this preparation as bit-for-bit artifact reproducible.

The command performs these guarded steps:

- validate the dependency lock, selected nodes, tools, run ID, and exact locked checkout;
- create an isolated detached worktree and apply the commit-bound preparation patch;
- install the exact required Ansible collections and syntax-check both playbooks before POS;
- reject foreign, partial, or split allocations;
- create or verify one current reservation;
- allocate both nodes together and verify their shared allocation owner;
- record newly imaged SSH host keys in a run-scoped ignored file and reject later changes;
- reuse upstream imaging, Linux, Kubernetes, CNI, storage, and GRE roles;
- install exact direct Python packages, checksum-verified yq, and exact Helm;
- stop before every Open5GS and srsRAN deployment role.

It never calls `deploy.sh`, never frees an allocation, never ignores reservation failure, and never rolls back a partially modified testbed automatically.

After a successful preparation, load the ignored private authority and SLICES-context variables:

```sh
source .synthran/preparations/network-001/authority.env
INVENTORY=.synthran/preparations/network-001/hosts.ini
```

The authority file contains raw owner, reservation and allocation identifiers plus project and experiment names with mode `0600`. It is written incrementally as provider IDs become known so a later failure remains recoverable. Do not print, copy, or commit it. The sibling manifest and log contain only fingerprints and sanitized facts.

## 4. Run read-only live preflight

```sh
python -m synthran doctor \
  --inventory "$INVENTORY" \
  --evidence-out .synthran/preflight.json
```

`doctor` reads authority and context from the exported `SYNTHRAN_OWNER`, `SYNTHRAN_RESERVATION_ID`, `SYNTHRAN_ALLOCATION_ID`, `SYNTHRAN_SLICES_PROJECT`, and `SYNTHRAN_SLICES_EXPERIMENT` variables. Explicit CLI arguments remain available and override the environment.

The POS 2.5.35 adapter queries `pos calendar list --filter owner=... --json` and `pos allocations show NODE`. It then checks strict SSH identity, exact remote tools, the empty Ready Kubernetes cluster, networking support, and every digest-addressed image. Any mismatch is terminal.

READY evidence is bound to the exact dependency-lock bytes, inventory, authority fingerprints, SLICES project and experiment fingerprints, controller versions, and complete required check set. It is valid for 15 minutes.

## 5. Explicitly deploy the 5G network

```sh
python -m synthran network deploy \
  --inventory "$INVENTORY" \
  --preflight-evidence .synthran/preflight.json \
  --run-id network-001
```

Deployment creates a separate isolated worktree, applies the locked narrow deployment patch, passes immutable Open5GS and srsRAN commits, pins eight images by digest, deploys one slice and one srsUE, and writes sanitized run artifacts. It never reserves, allocates, images, resets, or rebuilds nodes.

A successful deployment ends as `deployed-unverified`; that is not path proof.

## 6. Record network path proof

```sh
python -m synthran network verify \
  --inventory "$INVENTORY" \
  --run-id network-001 \
  --timeout 120
```

Verification requires exactly one run-owned Ready gNB, srsUE, and selected UPF. It checks locked image IDs, gNB cell activation, `tun_srsue1`, its PDU address and route, and the UPF `ogstun` route. Full success writes ignored network evidence and marks the deployment manifest `path-proven`. Re-running `verify` on an already `path-proven` network performs read-only reproof idempotently.

## 7. Run the integrated IoT-to-5G experiment

Once the network manifest is `path-proven` and `network-evidence.json` is ready, preview and execute the deterministic ten-sensor experiment:

```sh
synthran experiment plan \
  --network-run-id network-001 \
  --run-id exp-001

synthran experiment run \
  --inventory "$INVENTORY" \
  --network-run-id network-001 \
  --run-id exp-001
```

Controller privileges: Duckburg does **not** require `sudo`. SynthRAN automatically executes privileged TUN interface setup (`tunslip6` and `tun0` at `fd00::1/64`) and TCP ingress on the root core node (`inventory.core_node`) via a strict loopback-only reverse SSH tunnel.

Render persisted acceptance evidence without touching live state:

```sh
synthran experiment verify --run-id exp-001
```

See the [integrated experiment guide](experiment.md) for full scenario details, topology, artifacts, and acceptance criteria.

## Failure and recovery

Do not reuse a preparation or deployment run ID. A failure keeps a sanitized partial manifest and log. If preparation failed after imaging or reset began, inspect the named stage and preserve the artifacts; do not guess resource names, broadly delete, or automatically free the allocation.

If preflight finds an existing `open5gs` namespace, stop. Verify ownership and use a separate operator-approved teardown procedure.

## Safety boundary

- The user executes resource preparation, deployment, verification, experiments, and infrastructure teardown.
- Resource preparation is explicit and stops before 5G deployment.
- Network deployment is a separate explicit operation and never changes reservations or base node setup.
- Experiment execution never reserves nodes or silently deploys the network.
- Codex may implement and test offline code and interpret operator output, but does not execute live SLICES mutations.
- No SLICES or golden-path success is claimed without operator-provided evidence.
