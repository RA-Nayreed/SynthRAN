# Operator Guide

## Current capability

The golden-path network code implements the complete guarded lifecycle: offline validation, read-only live preflight, an explicit deployment in an isolated locked worktree, sanitized run artifacts, and read-only gNB/srsUE/tunnel/UPF verification. The network milestone is not accepted until an operator runs it on SLICES and supplies the resulting evidence.

The live path is deliberately narrower than the offline inventory parser:

~~~text
separate Open5GS core and srsRAN nodes
+ one RFSIM srsUE
+ profile=default
+ monitoring disabled
+ an existing empty and Ready Kubernetes cluster
~~~

The checked-in file under tests/fixtures/ is test data, not a deployment inventory. Create a real untracked inventory for allocated nodes. Never commit it.

Run every SynthRAN command on Linux. Live commands require a SLICES management frontend, or another Linux controller that has the SLICES pos CLI and strict SSH access to the nodes.

## Prepare the controller

After pulling this change, reconcile and activate the named environment because ansible-core is now a direct locked dependency:

~~~sh
conda env update --file environment.yml --prune
conda activate synthran
python -c "import os; assert os.environ.get('CONDA_DEFAULT_ENV') == 'synthran'"
python -m synthran deps sync
~~~

The operator must already have:

- one active reservation covering both selected nodes;
- one owned allocation containing both nodes;
- known SSH host keys and non-interactive access;
- both nodes visible as Ready in an existing Kubernetes cluster;
- Multus, OVS CNI, and the NetworkAttachmentDefinition CRD;
- no existing open5gs namespace;
- Helm v3 and the locked /usr/local/bin/yq on the RAN node;
- jq, the Python Kubernetes client, and the exact locked subscriber-bootstrap Python packages on the core node;
- the Python Kubernetes client on the RAN node.

Preflight fails closed if any item is missing or ambiguous. It does not reserve, allocate, boot, install, or modify anything.

## 1. Offline validation and plan

~~~sh
python -m synthran doctor \
  --offline --inventory /path/to/real-hosts.ini

python -m synthran network deploy \
  --dry-run --inventory /path/to/real-hosts.ini
~~~

Add --json only to the dry-run command for machine-readable redacted output.

## 2. Read-only live preflight

Use identifiers copied from the operator's current SLICES/POS state:

~~~sh
python -m synthran doctor \
  --inventory /path/to/real-hosts.ini \
  --owner OPERATOR \
  --reservation-id RESERVATION_ID \
  --allocation-id ALLOCATION_ID \
  --evidence-out .synthran/preflight.json
~~~

The POS adapter is validated against POS 2.5.35. It calls `pos calendar list --filter owner=OPERATOR --json`, requires exactly one matching numeric calendar ID, and verifies its `owner`, `nodes`, `start_date`, and `end_date`. It verifies each node allocation through `pos allocations show NODE` using the returned string `id` and `owner`. A provider command or output change is a terminal preflight failure; do not bypass it. Adapt and test the parser against operator-supplied value-free structural output.

READY evidence contains fingerprints rather than raw authority identifiers and is valid for 15 minutes. Run deployment promptly or rerun the doctor.

## 3. Explicit network deployment

Choose a unique lowercase run ID. Removing --dry-run is the explicit modifying action:

~~~sh
python -m synthran network deploy \
  --inventory /path/to/real-hosts.ini \
  --owner OPERATOR \
  --reservation-id RESERVATION_ID \
  --allocation-id ALLOCATION_ID \
  --preflight-evidence .synthran/preflight.json \
  --run-id network-001
~~~

Deployment:

- never creates or ignores a reservation;
- revalidates fresh evidence before creating a run directory;
- creates .synthran/runs/network-001/worktree detached at the locked 5g_ansible commit;
- installs only locked kubernetes.core;
- uses the locked transitive Git commits and eight Linux AMD64 image digests;
- applies and records the hash of the reviewed upstream boundary patch;
- keeps both remote dependency checkouts below a unique run-scoped directory;
- refuses to install host packages, restart kubelet/CoreDNS, download tools, deploy the WebUI, or enable slice two;
- runs the SynthRAN-owned narrow wrapper, not upstream deploy.sh or the boot/setup playbook;
- creates one srsUE and applies the run ID to Kubernetes resources;
- writes only sanitized logs and a partial manifest on a command failure.

A successful command leaves the manifest at deployed-unverified. That is not proof that the 5G path works.

## 4. Record network path proof

The verification command is read-only and requires the matching deployment manifest:

~~~sh
python -m synthran network verify \
  --inventory /path/to/real-hosts.ini \
  --run-id network-001
~~~

It requires exactly one run-owned, Running, Ready gNB pod, srsUE pod, and slice-one UPF pod. It also checks the primary and helper image IDs against the lock, requires the gNB log to report an activated cell, proves tun_srsue1 is UP with a 12.1.0.0/16 PDU address and route, and proves the selected UPF routes that network through ogstun.

Success writes .synthran/runs/network-001/network-evidence.json and changes the manifest status to path-proven. These ignored local files are the evidence the operator supplies for golden-path acceptance. They do not prove any later MQTT or IoT workload.

## Failure and recovery

Do not reuse a run ID. A failed deployment keeps its sanitized log, isolated worktree, and manifest with the failing stage. If any Kubernetes resources were created, preserve the artifacts and inspect only resources carrying that run ID. Network teardown remains a separate operator action; no SynthRAN experiment command tears down the base deployment.

If preflight finds an existing open5gs namespace, stop. Verify ownership and use the separate operator teardown procedure; never relabel, overwrite, or broadly delete an unknown deployment.

## Safety boundary

- The user owns reservations, allocations, deployment, experiment execution, and infrastructure teardown.
- No SynthRAN command reserves or boots nodes.
- Network deployment is a separate explicit operation.
- network verify is read-only.
- Future experiment runs will never reserve nodes or silently deploy the network.
- No SLICES or golden-path success is claimed without operator-provided evidence.
