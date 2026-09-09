# SynthRAN R2Lab handoff — PR #7

## Scope

Repository: `RA-Nayreed/SynthRAN`. Branch: `feat/r2lab-rfsim-parity`.
Target: `main`, through [PR #7](https://github.com/RA-Nayreed/SynthRAN/pull/7).

SynthRAN generates a deterministic Ambient-IoT event trace and replays decoded
events as MQTT traffic over a real 5G user plane. This change repairs the R2Lab
transport and deployment lifecycle. It does not change the source model or
establish new scientific results.

Read this handoff, the current PR diff, and the referenced upstream files before
continuing. The previous handoff's requirement for qhat03 on MBIM session 1 is
superseded by the single-DNN workflow below. Do not merge until a clean physical
run passes the acceptance criteria.

## Upstream basis

The implementation was compared with:

- [5g_ansible UE setup](https://github.com/sopnode/5g_ansible/blob/a0149fc0dde39e2872945a0f3c91e804ece52d4f/roles/r2lab/ue/setup/tasks/main.yml)
  and [UE connection](https://github.com/sopnode/5g_ansible/blob/a0149fc0dde39e2872945a0f3c91e804ece52d4f/roles/r2lab/ue/connect/tasks/main.yml).
- R2Lab's [physical 5G demo](https://github.com/sopnode/oai5g-rru/blob/9d7f2df8e98527c1a3b05c6352b167e8e9ce7c19/README.md),
  [prepare-ue](https://github.com/sopnode/oai5g-rru/blob/9d7f2df8e98527c1a3b05c6352b167e8e9ce7c19/quectel-utils/prepare-ue),
  [config-ue](https://github.com/sopnode/oai5g-rru/blob/9d7f2df8e98527c1a3b05c6352b167e8e9ce7c19/quectel-utils/config-ue),
  [start.sh](https://github.com/sopnode/oai5g-rru/blob/9d7f2df8e98527c1a3b05c6352b167e8e9ce7c19/quectel-utils/start.sh),
  and [stop.sh](https://github.com/sopnode/oai5g-rru/blob/9d7f2df8e98527c1a3b05c6352b167e8e9ce7c19/quectel-utils/stop.sh).

`5g_ansible` connects a UE's selected DNN using `start.sh -F DNN` on `wwan0`.
R2Lab's `-S` option adds a second simultaneous DNN to the same UE. An explicit
slice SD does not itself require that option or MBIM session 1. The reference
experiment assigns one DNN to each UE, so both UEs use MBIM session 0 on their
own hosts. This also matches the existing core subscriber configuration.

Use the helpers installed on the R2Lab images. SynthRAN does not replace those
helpers, implement a second MBIM dialer, or write modem PDP contexts directly.
Differences between installed helpers and the source versions above must be
recorded when investigating a physical failure.

## Reference experiment

Scenario: `scenarios/r2lab-reference-oai-srsran.yml`.
Core: OAI on `sopnode-f2`. RAN: srsRAN on `sopnode-f3` with N320.
Broker: `sopnode-f2`, reached through the UPF.

| UE | IMSI | Source role | Slice / DNN | MBIM session | Host interface | Expected address |
|---|---|---|---|---|---|---|
| qhat01 | 001010000000006 | WPT, 1000 ms sensing | slice1 / internet | 0 | wwan0 | 12.1.1.x |
| qhat03 | 001010000000008 | Hybrid, 500 ms sensing | slice2 / streaming | 0 | wwan0 | 14.1.1.x |

The corresponding source roles are `uesim01` and `uesim02` in RFSIM. Preserve
the scenario seed, duration, energy settings, PLMN, SST/SD, ARFCN, gain, and
N320 management/data addresses (`192.168.235.105` for both).

Before the gNB starts, the MBIM preparation role runs the equivalent of:

```sh
# On qhat01
prepare-ue --mode=mbim --dnn=internet

# On qhat03
prepare-ue --mode=mbim --dnn=streaming --nssai=01.100000
```

After the gNB passes its startup gate, the connection role uses `stop.sh` and
`start.sh -q -F internet` or `start.sh -q -F streaming`. It unsets inherited
`DNN1` and requests IPv4. `-q` suppresses the helper's public Internet ping;
SynthRAN validates the experiment's UPF and MQTT endpoint instead.

QFIT MBIM devices follow the same selected-DNN preparation when defined in the
effective profile. QMI devices retain the upstream `qhat-init`, `quectel-CM`,
and `ci_ctl_qtel.py` procedure. They are outside this two-QHAT acceptance run.

## Lifecycle and retained safeguards

1. Resolve the saved R2Lab slice identity and verify Faraday SSH before any SOP
   allocation or reset. Use that identity in the generated inventory and jumps.
2. Reconcile reservations through `deployment/scripts/reserve_sop.py`.
3. Prepare the selected radio and UEs before deploying the core and gNB.
   N3xx radios retain the proved OFF state, 20-second off interval, ON transition,
   and 60-second boot interval from the earlier physical diagnosis. These
   intervals use noninteractive waits on the controller; they do not read or
   change the SSH terminal, and cannot be skipped with a pause prompt.
4. Deploy the N3xx gNB once. Wait for one pod, Running/Ready state, completed N2,
   and a gNB-start marker. Observe the same pod UID and restart count for another
   15 seconds. Startup failure preserves the release and diagnostic artifacts.
5. Attach UEs through the installed upstream helpers. Read the SIM identity,
   configured DNN/NSSAI, interface, activated MBIM session, and modem IP settings.
   Require a single matching host IPv4 address and the selected slice subnet.
6. Prove the UPF path, broker route, and source-bound MQTT TCP connection. Pass
   the observed interface/address to the publisher and recheck before replay.
7. Append physical bindings to the existing cluster attestation, then reconcile
   the model, publisher, and broker artifacts.

The former direct secondary-session activation, `wwan0.1` construction,
post-preparation USB recovery, standalone CID-2 deletion, and mutating AT
diagnostic block have been removed. The duplicate reservation implementation
and redundant inventory identity overrides have also been removed.

## Running and resuming

Use a clean working tree on the PR branch:

```sh
cd ~/SynthRAN
git status --short
git switch feat/r2lab-rfsim-parity
git pull --ff-only origin feat/r2lab-rfsim-parity
git rev-parse HEAD
```

Record the resulting commit with the run. Preserve local changes before switching
branches; do not use a hard reset to follow this handoff.

Run a full deployment for the corrected session mapping:

```sh
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml
```

After a successful matching deployment, repeat its workload with:

```sh
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml --workload-only
```

Workload-only and resume observe existing modem sessions and routes. They do
not stop/start a modem, change its radio state, create an interface, or replace
a route. A disconnected or mismatched session stops the run and requires a
full deployment. An old session-1 fingerprint cannot be reused or silently
migrated to session 0.

`./deploy.sh --resume results/<failed-run-id>` remains suitable for a failure
after the corrected deployment was attested and its physical sessions remain
healthy. A failure during initial UE attachment cannot be repaired by resume.

## Terminal disconnects and controller state

The entrypoint completes interactive selection, credentials, reservations, and
dependency preparation before starting its independent deployment controller.
Stay connected through those preparation steps. When the entrypoint prints the
Ansible and controller log paths, Ansible and subsequent reconciliation can
continue after the SSH terminal disconnects. The controller retains the
deployment lock for its entire lifetime, so another run cannot overlap it.

Ansible reads no terminal input and writes directly to `ansible.log`. The
terminal's progress viewer is independent of that writer. The controller writes
its PID to `controller.pid`, its final exit status to `controller-exit-code`,
and its diagnostics to `deployment.log`. `source-revision.txt` records the
checkout's commit at run creation. Keep the checkout unchanged during a run.

After reconnecting, set the actual run directory and read its existing log:

```sh
cd ~/SynthRAN
R2LAB_RUN=results/REPLACE_WITH_RUN_ID
tail -F "$R2LAB_RUN/ansible.log"
```

Stopping this log viewer does not stop deployment. After deployment finishes:

```sh
cat "$R2LAB_RUN/controller-exit-code"
cat "$R2LAB_RUN/deployment.log"
python3 -m json.tool "$R2LAB_RUN/summary.json"
```

Exit status zero means the controller completed successfully. It does not mean
every MQTT event arrived: check the summary's identity, coverage, and delivery
fields. A missing exit-status file means completion has not been recorded;
inspect the PID and log rather than assuming success or starting another run.

Ctrl+C in the original deployment terminal cancels the controller and its active
local child process. To cancel after reconnecting, first verify the recorded PID:

```sh
R2LAB_CONTROLLER=$(cat "$R2LAB_RUN/controller.pid")
ps -p "$R2LAB_CONTROLLER" -o pid,ppid,etime,args
```

Only if that process is this run's `run_deployment.sh --worker`, stop it with
`kill -TERM "$R2LAB_CONTROLLER"`. Keep the logs and allow the process to release
the deployment lock. Cancellation leaves already created remote resources for
inspection.

The reported `20260909T042818Z` log contains the obsolete tasks `Override the
generated Faraday inventory identity` and `Override R2Lab endpoint jump
identities`. Those tasks were removed in commit `590a404`. That run therefore
does not demonstrate execution of the corrected PR head. Finish or stop its
remaining controller before updating the checkout and running again. Updating
files does not repair an already running process.

## Physical acceptance

Local tests exercise command fixtures; they do not establish R2Lab hardware
success. On the actual testbed, require all of the following before merging:

- One clean N320 gNB startup and stable readiness, with unchanged RF settings.
- Both SIM identities read from modem diagnostics; qhat01 attached to `internet`
  and qhat03 configured with `streaming` and NSSAI `01.100000`.
- Both MBIM session-0 queries activated, with modem IPs matching their respective
  `wwan0` addresses and expected slice pools.
- UPF reachability, broker routes through `wwan0`, and MQTT receipts for the
  exact generated event IDs. Publisher records must show the proved source IPs.
- A workload-only repetition with no modem attach, power, interface, or route
  mutations, and complete deployment identity evidence in `summary.json`.

Retain `ansible.log`, `deployment.log`, `controller.pid`, `controller-exit-code`,
`source-revision.txt`, `deployment-fingerprint.json`, `live-deployment-evidence.json`,
`gnb.log`, `gnb-health.txt`, `physical-ue-*.log`, publisher records, broker receipts,
and `summary.json`. Failed gNB startup additionally retains `gnb-describe.txt`;
failed MBIM activation retains the helper output and `qhat-check` output in
`physical-ue-<host>-attach.log`. Correlate a UE failure with the AMF/SMF log window.

If installed R2Lab helpers behave differently, retain their output and version
before adjusting the integration. Do not add another modem dialer, silently
substitute a DNN, or label configured identities as observed evidence.

## Local validation

With the deployment dependencies installed:

```sh
python -m unittest discover -s tests -v
bash -n deploy.sh
bash -n deployment/scripts/run_deployment.sh
```

The tests cover selected-DNN preparation for QHAT/QFIT, real Ansible task flow
with command fixtures, full attachment, read-only reuse, retained failures,
wrong SIMs, stale addresses, wrong sessions/NSSAI, management-route rejection,
publisher address changes, legacy fingerprint rejection, and gNB stability.
Process tests close a real pseudo-terminal while Ansible waits, then require
continued execution and reconciliation, unchanged terminal settings, a retained
deployment lock, correct failure status, and cancellation of local child processes.
