# Research measurement peer

Controlled capacity calibration and background-load experiments must terminate **outside the 5G core host**.

## Required topology

```text
srsUE PDU
-> tun_srsue1
-> srsRAN / 5G user plane
-> Open5GS UPF
-> core egress / NAT
-> external measurement peer
```

For the reviewed two-node SLICES virtual inventory, the prepared RAN node is the measurement peer. The core node is never the iperf3 server for controlled research measurements.

A server on the core host can create a same-host Kubernetes/hairpin path in which the UE binds its PDU address but the flow does not exercise the intended external egress. Such a run can look reachable while being scientifically invalid for external user-plane capacity/load claims.

## Runtime contract

The run-owned iperf3 lifecycle must preserve:

- the selected server is the prepared external measurement node, not `inventory.core_node`;
- an explicitly supplied target is proven assigned to that selected node;
- the UE client binds the live PDU and the exact target route uses `tun_srsue1`;
- stale recovery targets only the exact SynthRAN-owned server signature;
- listener ownership is proven from the run-owned process/socket state, not from an untrusted PID file alone;
- cleanup runs on the same peer that started the server and fails closed when ownership is ambiguous.

Temporary server state remains run-scoped below `/tmp/synthran-research/<run-id>/` on the peer.

## Operator target selection

Inspect the prepared RAN node:

```bash
ansible -i "$INVENTORY" ran_node -m shell -a '
hostname
ip -4 -o addr show
ip -4 route show default
'
```

Choose its provider-facing IPv4 address:

```bash
MEASUREMENT_PEER_IP=<prepared-ran-node-provider-ip>
```

Do not use:

- the core-node provider address;
- a Kubernetes/Post5G LoadBalancer address;
- a stale address copied from an older network epoch.

## Calibration

```bash
python -m synthran experiment research calibrate \
  --inventory "$INVENTORY" \
  --network-run-id "$NETWORK_RUN_ID" \
  --target "$MEASUREMENT_PEER_IP" \
  --duration-seconds 10 \
  --out .synthran/research/capacity.json
```

Fractional loaded conditions must use the same peer and a reference calibration valid for the current network/dependency epoch.

## Loaded pre-window readiness

Readiness should prove the transport that defines the experimental condition.

For loaded runs, SynthRAN does not use ICMP success as the veto for whether iperf3 load may begin. Instead it proves:

1. the exact target route is through `tun_srsue1`;
2. the run-owned iperf3 server is listening on the external peer;
3. the UE iperf3 client is bound to the live PDU address;
4. the client's TCP control connection becomes genuinely `ESTABLISHED` before the measurement window opens.

`CLOSE-WAIT` is not accepted as readiness.

UDP data then runs under that established iperf3 control session. ICMP remains an independent RTT observation during the measurement window.

Baseline has no load transport to prove, so it retains its bounded baseline target-reachability check.

## Evidence required for a loaded result

Before a run is scientifically usable, confirm the applicable persisted validity evidence shows:

- target route through `tun_srsue1`;
- external peer/server ownership proven;
- load control connection established before the window;
- target load achieved;
- path instrumentation remained healthy;
- post-window network proof succeeded;
- run-owned cleanup succeeded and the base network was reproven.

A failed or same-host calibration remains diagnostic evidence and must not be reused as a fractional reference.

## Current live acceptance

The current accepted research epoch used:

```text
network_run_id:         network-acceptance-20260818-09
measurement peer:       sopnode-f3 / 172.28.2.95
calibration artifact:   calibration-20260819-external-08.json
reference capacity:     66,366,402 bps
campaign:               campaign-20260819-06
```

The campaign completed all 12 blocked runs across baseline, 50%, 80%, and 95% of the reference capacity. All nine loaded runs sustained their target aggregate UDP goodput and the external receiver reported zero UDP packet loss.

The complete result, preservation identifiers, and interpretation limits are in [`results.md`](results.md).

## Historical reason for this invariant

Earlier same-host tests showed why a core-host target was unsafe: the transport could collapse into a Kubernetes/hairpin path and the iperf3 control state could look misleading even though the intended external UE path had not been established correctly.

Those failures are intentionally retained as diagnostic history in [`live-results-20260818.md`](live-results-20260818.md). They must not be promoted into current campaign evidence.
