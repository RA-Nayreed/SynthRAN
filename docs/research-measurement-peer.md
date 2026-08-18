# Research measurement peer

Controlled capacity calibration and background-load experiments must terminate outside the 5G core host.

## Required topology

The supported measurement path is:

```text
srsUE PDU address
  -> tun_srsue1
  -> srsRAN / 5G user plane
  -> Open5GS UPF
  -> core egress / NAT
  -> external measurement peer
```

For the current two-node SLICES inventory, the prepared RAN node is the measurement peer. The core node is never used as the iperf3 server for controlled research measurements.

This distinction is intentional. A server on the core host can create a same-host Kubernetes/hairpin path in which the UE binds to its PDU address but the server observes the flow through the pod network. Such a run can look reachable while failing to represent the intended external user-plane path.

## Runtime contract

`start_owned_iperf_server()` defaults to `inventory.ran_node` and refuses to use `inventory.core_node` as the research measurement server.

The server lifecycle remains run-owned:

- stale recovery only targets the exact run-owned iperf3 signature;
- the listener is proven by matching the unique run-owned command line and the exact listening socket inode;
- cleanup runs on the same measurement node that started the server;
- the workspace and PID file remain below `/tmp/synthran-research/<run-id>/`;
- cleanup fails closed when ownership cannot be proven.

The low-level lifecycle also accepts an explicit `server_node` and `target`. When both are supplied, SynthRAN proves that the target IPv4 address is assigned to that prepared inventory node before starting iperf3.

## Operator target selection

The CLI still requires an explicit target address. Use the provider-facing IPv4 address of the prepared RAN node, not the core-node address and not the Post5G NRF LoadBalancer address.

Inspect the prepared RAN node before calibration:

```sh
ansible -i "$INVENTORY" ran_node -m shell -a '
hostname
ip -4 -o addr show
ip -4 route show default
'
```

Choose the RAN-node IPv4 on the provider network that is reachable after UPF egress. Then use that same address for calibration and all loaded campaign conditions.

```sh
MEASUREMENT_PEER_IP=<ran-node-provider-ip>

python -m synthran experiment research calibrate \
  --inventory "$INVENTORY" \
  --network-run-id "$NETWORK_RUN_ID" \
  --target "$MEASUREMENT_PEER_IP" \
  --duration-seconds 10 \
  --out .synthran/research/capacity.json
```

Loaded runs must use the same endpoint:

```sh
python -m synthran experiment research run \
  --inventory "$INVENTORY" \
  --campaign-id "$CAMPAIGN_ID" \
  --network-run-id "$NETWORK_RUN_ID" \
  --run-id "$RUN_ID" \
  --condition load50 \
  --seed 424242 \
  --probe-target "$MEASUREMENT_PEER_IP" \
  --target-fraction 0.5 \
  --reference-capacity-bps "$REFERENCE_CAPACITY_BPS"
```

## Pre-window target readiness

The readiness proof must match the transport that defines the experimental condition.

For a loaded condition, SynthRAN does **not** require ICMP echo replies before the measurement window. Instead it proves the actual load transport:

1. the exact target `/32` route is through `tun_srsue1`;
2. the run-owned iperf3 server is started on the external measurement peer;
3. the UE iperf3 client is bound to the live PDU address;
4. the client's TCP control connection becomes `ESTABLISHED` to the peer before the measurement window opens.

Only after those checks pass is `pre_window.target_ready` set to true. UDP data then runs under that established iperf3 control session.

Baseline conditions have no load transport to prove, so they retain the bounded pre-window ICMP reachability check.

ICMP remains useful during every measurement as RTT evidence. The continuous RTT probe records every attempt and timeout, but an external peer that does not answer ICMP must not veto an otherwise proven loaded iperf3 transport.

`CLOSE-WAIT` is not accepted as readiness. The load control connection must be genuinely established.

## Evidence expectations

Before accepting a loaded result, confirm all of the following:

1. the effective UE route to the peer is through `tun_srsue1`;
2. the iperf3 TCP control connection becomes established before the window and remains healthy while UDP data is running;
3. the external peer receives the flow after core/UPF egress rather than from a Kubernetes pod address;
4. the load client and run-owned server complete normally;
5. the post-window network proof succeeds;
6. telemetry validity gates also pass.

A failed or same-host calibration is debugging evidence only. It must not be reused as reference capacity for campaign fractions.

## 2026-08-18 live acceptance

The same-host core target was rejected after diagnosis because it produced a Kubernetes/hairpin path and an iperf3 UDP control connection in `CLOSE-WAIT`.

A managed cross-host diagnostic to the prepared RAN node proved the intended topology. With the UE bound to its PDU address and routed through `tun_srsue1`, the external peer received the flow after core/UPF egress. Both iperf3 processes exited successfully and a 1 Mbps UDP test delivered approximately 995 Kbps with zero packet loss.

After the measurement-peer fix was merged, the network was redeployed under the current dependency-lock epoch as:

```text
network-acceptance-20260818-04
Result: PATH PROVEN
```

The prepared RAN node's provider-facing address was:

```text
sopnode-f3 -> 172.28.2.95
```

A fresh external-peer capacity calibration then completed successfully:

```text
artifact: .synthran/research/calibration-20260818-external-01.json
network_run_id: network-acceptance-20260818-04
target: 172.28.2.95
ue_interface: tun_srsue1
reference_capacity_bps: 66,687,096
```

That value is the current accepted reference for subsequent fractional load experiments on this network run. Historical same-host capacity results remain debugging evidence only.

The first 1 Mbps production-path smoke run after calibration, `smoke-20260818-01-udp1m`, is **invalid diagnostic evidence**. It never opened the measurement window because the old runtime required three successful ICMP replies before starting iperf3. Cleanup reproved the base network. That failure established the transport-aware readiness correction documented above; the invalid run must not be reused or reclassified.
