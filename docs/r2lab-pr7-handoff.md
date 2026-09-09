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
- [5g_ansible's gNB deployment check](https://github.com/sopnode/5g_ansible/blob/a0149fc0dde39e2872945a0f3c91e804ece52d4f/roles/5g/srsRAN/deploy/tasks/deploy_with_check.yml),
  the pinned [srsRAN Helm launch template](https://github.com/turletti/srsran-helm/blob/8dfb9890d127734cdcd6eee9df8c5d09b1a8076a/charts/srsran-gnb/templates/deployment.yaml),
  and its [N320 values](https://github.com/turletti/srsran-helm/blob/8dfb9890d127734cdcd6eee9df8c5d09b1a8076a/charts/srsran-gnb/values-n320-n78-20MHz.yaml).
- The srsRAN fork's [startup banner](https://github.com/turletti/srsRAN_Project/blob/5883162f190a97e219a4609b184b032f91f247e1/apps/services/application_message_banners.h)
  and [N2 connection output](https://github.com/turletti/srsRAN_Project/blob/5883162f190a97e219a4609b184b032f91f247e1/lib/ngap/gateways/n2_connection_client_factory.cpp).

`5g_ansible` connects a UE's selected DNN using `start.sh -F DNN` on `wwan0`.
R2Lab's `-S` option adds a second simultaneous DNN to the same UE. An explicit
slice SD does not itself require that option or MBIM session 1. The reference
experiment assigns one DNN to each UE, so both UEs use MBIM session 0 on their
own hosts. This also matches the existing core subscriber configuration.

SynthRAN combines these upstream components with its own inventory, workload,
and evidence handling; it is not a verbatim copy of one R2Lab repository.
Earlier integration checks assumed helper options and diagnostic output that
differed from the installed images. The regressions now include the reported
helper usage and actual qhat03 PDP contexts.

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
prepare-ue --dnn=internet

# On qhat03
prepare-ue --dnn=streaming --nssai=01.100000
```

The installed helper in physical run `20260909T101521Z` advertises only `--dnn`,
`--dnn2`, `--nssai`, and `--nssai2`. Passing `--mode=mbim` failed with exit code 2
on both QHATs before the helper could configure either modem. The MBIM role omits `--mode`;
the referenced upstream helper also defaults to MBIM without that option.
QMI preparation remains separate. Do not replace installed helpers merely to
make an unsupported argument work.

After the gNB passes its startup gate, the connection role uses `stop.sh` and
`start.sh -q -F internet` or `start.sh -q -F streaming`. It unsets inherited
`DNN1` and requests IPv4. `-q` suppresses the helper's public Internet ping;
SynthRAN validates the session, broker route, and source-bound MQTT TCP connection.

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
4. Deploy the N3xx gNB once, using `exec stdbuf -oL -eL` before the chart's
   existing gNB command so console messages flush without a terminal or UE
   traffic. Wait for one pod, Running/Ready state, completed N2, and a gNB-start
   marker. Observe the same pod UID and restart count for another 15 seconds.
   Startup failure preserves the release and diagnostic artifacts.
5. Attach UEs through the installed upstream helpers. Read the SIM identity,
   configured DNN/NSSAI, interface, activated MBIM session, and modem IP settings.
   Require a single matching host IPv4 address and the selected slice subnet.
6. Verify the broker route and source-bound MQTT TCP connection through the
   observed modem interface. Pass that interface/address to the publisher,
   which checks the address again immediately before replay.
7. Append physical bindings to the existing cluster attestation, then reconcile
   the model, publisher, and broker artifacts.

The former direct secondary-session activation, `wwan0.1` construction,
post-preparation USB recovery, standalone CID-2 deletion, and mutating AT
diagnostic block have been removed. The duplicate reservation implementation
and redundant inventory identity overrides have also been removed.

The current cleanup removes the repeated profile load and slice lookup, an
extra publisher address check, and a redundant binding-count assertion. The
validated deployment contract supplies the selected DNN and UPF endpoint.
The radio role starts with the requested OFF transition; the initial PDU-state
precondition was redundant because OFF and ON are verified after each command.
The working power intervals and transition checks remain.

An UPF ICMP reply is no longer a prerequisite for MQTT traffic. Session, address,
route, and source/interface-bound TCP checks remain, so a management-network
route or unreachable broker still stops the workload.

## Modem diagnostic compatibility

The supplied qhat03 diagnostics contain the base context `streaming` and
contexts named `streaming_EMBB100000` carrying NSSAI `01.100000`. The previous
parser searched for NSSAI only on an exact `streaming` APN and would reject
this observed configuration after gNB startup. It now accepts that exact eMBB
suffix for SST 1 while requiring the selected SD and matching NSSAI in the same
context. Another DNN, another SD, or a missing base DNN still fails validation.
The upstream helper remains responsible for modem configuration.

QMI diagnostics can contain both a 15-digit IMEI and a 15-digit IMSI. The parser
now reads the labelled IMSI and accepts the helper's `USB Mode: 0 (QMI)` output
as well as the raw USB-mode response. It no longer mistakes the IMEI for a
second SIM identity. These QMI paths have local regression coverage; this
reference experiment still uses MBIM on qhat01 and qhat03.

## Startup timeout in run 20260909T103737Z

The supplied run passed N320 power preparation, both installed `prepare-ue`
calls, host preparation, Kubernetes, and transport setup. It then timed out at
the physical gNB gate after 301 seconds with pod
`srsran-gnb-868c957c8-xwq8c` reported as `Running`, `ready=true`.
The subsequently supplied `gnb.log` and `gnb-describe.txt` establish:

- The pod had zero container restarts and normal Kubernetes events. N3 was
  `192.168.3.203`; the radio interface was `192.168.235.240`.
- The N320 at `192.168.235.105` initialized its daughterboards, PLLs, and RPC
  server. The last visible line was a tick-rate warning, with no visible N2
  completion or gNB-start banner.
- The container still used `/usr/local/bin/gnb -c $CONFIG_FILE`, without the
  flushing prefix added in commit `3c83654`. This is evidence from the earlier
  failed run, not a physical test of that correction.
- The image was `r2labuser/srsran-gnb-uhd:v1.0`, digest
  `sha256:f22e391ff19bb4d838e24962f6429a64abae0bd6abd812f4be8c10f8af8fe690`.

`RTNETLINK answers: No such process` comes from the chart's best-effort default
route deletion. Neither that message nor the tick-rate warning alone establishes
a fatal radio failure. The saved output also does not establish completed
radio startup.

The pinned chart launches the gNB without a terminal and has no readiness
probe. Consequently, Kubernetes readiness alone does not prove N2 or radio
startup. The srsRAN source emits the N2 message and startup banner through
buffered stdout. A reproduction using the upstream banner header reached the
startup code while producing no visible stdout; `stdbuf -oL -eL` made both
messages visible while that same process remained running. The earlier test
fixture printed its messages immediately and missed this failure mode.

The launch correction retains the gNB binary, arguments, image, configuration,
and existing startup requirements.
The launch patch is idempotent and rejects an unexpected chart launch shape
before Helm. It does not add a terminal or wait for UE traffic to flush logs.
This fixes a reproduced observer defect; it does not prove that buffering was
the only cause of this physical run's timeout. The source examined above is
the fork's recorded revision, not an observed build identity from this pod.

Timeout output now includes the observed N2 and gNB-start signals, pod identity,
restart count, and return codes of the log and pod reads. A failed read cannot
satisfy the gate using partial output. The N2 completion message must be on one
line; an unrelated completed operation is insufficient. Explicit srsRAN process
errors fail the gate. Recoverable early UHD warnings retain their prior handling.

Failures print the last 80 console and application-log lines into `ansible.log`
and preserve the full captured files. The pinned N300/N320 values put the
application log at `/tmp/gnb.log`, while the chart's log sidecar tails
`/var/log/gnb.log`. The N3xx deployment disables that unused sidecar through the
chart's existing `start.logs: false` value. Collection reads the application
file directly from the `gnb` container. Console collection remains enabled.

Keep the saved failed-run directory. The evidence has now been reviewed; the
next physical check is a normal full deployment with the corrected launch.
A failed initial gNB startup has no attested deployment to resume, so
`--workload-only` and `--resume` cannot repair this run.

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

Run a full deployment for the corrected launch and modem validation:

```sh
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml
```

The new physical gNB pod should contain the `gnb` container without `gnb-logs`,
and its command should use `exec stdbuf -oL -eL /usr/local/bin/gnb -c ...`.
Require the recorded startup-gate result to pass before assessing UE attachment.

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
- Broker TCP reachability and routes through `wwan0`, and MQTT receipts for the
  exact generated event IDs. Publisher records must show the proved source IPs.
- A workload-only repetition with no modem attach, power, interface, or route
  mutations, and complete deployment identity evidence in `summary.json`.

Retain `ansible.log`, `deployment.log`, `controller.pid`, `controller-exit-code`,
`source-revision.txt`, `deployment-fingerprint.json`, `live-deployment-evidence.json`,
`gnb.log`, `gnb-health.txt`, `physical-ue-*.log`, publisher records, broker receipts,
and `summary.json`. Failed gNB startup additionally retains `gnb-describe.txt`
and `gnb-application.log`;
failed MBIM activation retains the helper output and `qhat-check` output in
`physical-ue-<host>-attach.log`. Correlate a UE failure with the AMF/SMF log window.

If installed R2Lab helpers behave differently, retain their output and version
before adjusting the integration. Do not add another modem dialer, silently
substitute a DNN, or label configured identities as observed evidence.

## Local validation

Validation on 9 September 2026 passed all 49 local tests, syntax checks for
`site.yml`, `workload.yml`, and `resume.yml`, Bash syntax checks, and formatting
and Python error checks for the changed files. Physical acceptance of these
corrections remains pending.

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
The actual qhat03 contexts are accepted while wrong DNN/SD variants are rejected.
QMI tests distinguish IMSI from IMEI and accept the labelled USB-mode output.
The full UE role succeeds when ping is unavailable and still stops if the
bound broker connection fails. Radio-role tests cover cold boot from ON or OFF
and failure to reach either requested power state.
Process tests close a real pseudo-terminal while Ansible waits, then require
continued execution and reconciliation, unchanged terminal settings, a retained
deployment lock, correct failure status, and cancellation of local child processes.
Preparation tests enforce the physical helper's reported option list and execute
the pinned upstream `prepare-ue` with its hardware commands replaced by local
fixtures. These checks prove command compatibility, not physical modem success.

The gNB regressions run the real Ansible launch tasks and a C process whose
startup messages remain buffered until flushed. They demonstrate failure with
the former launch and stable success with the corrected launch before any UE
traffic or process exit. They also cover individual missing startup signals,
failed Kubernetes reads, retained application/console diagnostics, and fatal
srsRAN errors. A separate local check applied the launch tasks twice to the
unmodified pinned Helm template and verified that only its launch prefix changed.
