# SynthRAN R2Lab handoff — upstream 5g_ansible parity

## Scope

Repository: `RA-Nayreed/SynthRAN`.

This handoff describes the simplified R2Lab deployment boundary. SynthRAN does
not maintain an independent R2Lab radio, gNB, or modem-management framework.
For R2Lab-specific deployment behavior it follows the pinned upstream
`sopnode/5g_ansible` implementation. SynthRAN remains responsible for the
Ambient-IoT model, immutable workloads, MQTT experiment replay, collection, and
result reconciliation.

The refactor was started from PR #7 head
`f18aa5a2ec1aa6c3c939c3655357bcf0293a8536` on the temporary branch
`refactor/r2lab-upstream-parity`.

## Upstream authority

Pinned upstream repository:

- `sopnode/5g_ansible`
- revision: `a0149fc0dde39e2872945a0f3c91e804ece52d4f`

The following R2Lab-owned files are intentionally byte-identical to that
revision and are protected by `tests/test_r2lab_upstream_parity.py`:

- `deployment/roles/r2lab/cleanup/tasks/main.yml`
- `deployment/roles/r2lab/rru/tasks/main.yml`
- `deployment/roles/r2lab/ue/setup/tasks/main.yml`
- `deployment/roles/r2lab/ue/connect/tasks/main.yml`
- `deployment/roles/5g/srsRAN/deploy/tasks/deploy_gnb.yml`
- `deployment/roles/5g/srsRAN/deploy/tasks/deploy_with_check.yml`

If one of these files needs a behavioral change, first determine whether that
change belongs upstream. Do not silently grow another SynthRAN fork of the
R2Lab deployment logic.

## What upstream owns on R2Lab

The active R2Lab provisioning sequence is the upstream sequence:

1. `r2lab/cleanup`
2. `r2lab/rru`
3. `r2lab/ue/setup`

After the 5G stack is deployed, R2Lab UE connection is performed with the
upstream `r2lab/ue/connect` role on Faraday, once for each selected qhat/qfit.
The role owns MBIM/QMI selection, selected-DNN connection, waiting for `wwan0`,
and the UPF route.

For N300/N320 with srsRAN, the upstream deployment role owns gNB startup. It
uses its own Helm readiness/stability behavior and its two-attempt N3xx
address-pair fallback. SynthRAN no longer adds a second N2/banner parser or a
separate gNB startup state machine.

## Removed SynthRAN R2Lab guardrails

The R2Lab path no longer uses the custom PR7 mechanisms that independently
implemented or validated:

- forced N3xx OFF -> wait -> ON -> wait state sequencing;
- custom `stdbuf` patching of the gNB launch;
- custom N2 and gNB-start log parsing;
- custom pod UID/restart-count startup gate;
- custom physical SIM/DNN/NSSAI/session/address parser;
- custom R2Lab modem binding contract;
- custom source-bound MQTT TCP proof before replay;
- the old `r2lab/ue_setup` role fork;
- the R2Lab-specific precondition in `network.yml`.

The corresponding custom gNB and modem-lifecycle tests were removed. Exact
upstream parity is tested instead.

The generic non-R2Lab `platform: physical` backend is separate and retains its
own `synthran/physical_ue` implementation. This refactor is intentionally scoped
to `platform: r2lab`.

## Minimal SynthRAN experiment glue

After upstream R2Lab UE connection, SynthRAN only needs enough information to
run its experiment. For the R2Lab publisher it:

1. resolves the configured N6-side MQTT broker address;
2. installs the broker host route through `wwan0`;
3. launches the SynthRAN workload replay using `--interface wwan0`;
4. fetches publisher records and broker/application receipts;
5. reconciles experiment results.

There is no separate R2Lab `synthran_physical_binding` requirement. The replay
code may read the configured interface to obtain the local source address for
the MQTT socket; that is publisher functionality, not a second modem-management
framework.

Result reconciliation still retains the generic SynthRAN deployment identity
and cluster provenance. For R2Lab it no longer requires custom physical binding
evidence. Generic `platform: physical` continues to use binding verification.

## Reference experiment

Current reference scenario:

`scenarios/r2lab-reference-oai-srsran.yml`

Current campaign choices are:

- OAI core on `sopnode-f2`;
- srsRAN on `sopnode-f3`;
- N320 radio;
- qhat01 and qhat03 as gateway UEs;
- MQTT broker on the N6 side at `sopnode-f2`.

qhat01 and qhat03 are reference-experiment selections, not hard-coded permanent
SynthRAN UEs. Other upstream-supported qhat/qfit devices should remain selectable
through scenario/profile/inventory configuration.

## Reservation versus deployment

SynthRAN still has code that resolves the user's SOP and R2Lab reservations.
That is orchestration needed to acquire resources before the upstream roles can
run; it is not an independent implementation of radio/gNB/modem behavior.
Authentication failures or reservation failures should stop before deployment.
Do not turn reservation handling into another hardware-state validation layer.

## Workload reuse

`--workload-only` keeps the SynthRAN concept of reusing a matching deployed 5G
stack, but the R2Lab UE connection step is again delegated to upstream
`r2lab/ue/connect`. Upstream may leave an already-working `wwan0` session alone
or reconnect it according to its own logic. SynthRAN no longer promises a
separate non-mutating modem-observation contract for R2Lab.

Prepared/immutable workload semantics belong to SynthRAN and must remain intact.
This is especially important for Experiment 2, where native, gap-permuted, and
periodic timing variants must use the same event identities and payloads.

## Validation before updating PR #7

Run locally on Duckburg from the refactor branch:

```sh
python -m pip install -e '.[test]'
python -m unittest discover -s tests -v
python -m compileall -q synthran
bash -n deploy.sh
git diff --check
```

Run the exact parity test explicitly:

```sh
python -m unittest tests.test_r2lab_upstream_parity -v
```

Also run Ansible syntax checks using a generated R2Lab inventory and resolved
variables before a live booking.

Do not update PR #7 until these local checks pass.

## Live acceptance

After local validation, run the normal reference scenario:

```sh
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml
```

If it fails in an upstream-owned R2Lab role, first determine whether the same
upstream `5g_ansible` operation fails. Do not immediately add a SynthRAN-specific
hardware guard or parser.

If upstream succeeds and the SynthRAN experiment glue fails, fix only the
adapter/experiment layer.

## Engineering rule

The boundary is intentionally simple:

```text
5g_ansible: R2Lab deployment and UE connectivity
SynthRAN:    experiment generation, replay, measurement, and analysis
```

For `platform: r2lab`, upstream behavior wins. Keep SynthRAN-specific code only
where it is required to perform the experiment after that deployment exists.
