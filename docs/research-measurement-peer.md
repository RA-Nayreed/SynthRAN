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

## Evidence expectations

Before accepting a loaded result, confirm all of the following:

1. the effective UE route to the peer is through `tun_srsue1`;
2. the iperf3 TCP control connection remains established while UDP data is running;
3. the external peer receives the flow after core/UPF egress rather than from a Kubernetes pod address;
4. the load client and run-owned server complete normally;
5. the post-window network proof succeeds;
6. telemetry validity gates also pass.

A failed or same-host calibration is debugging evidence only. It must not be reused as reference capacity for campaign fractions.

## 2026-08-18 diagnosis

A same-host target on the core node produced an iperf3 UDP control connection in `CLOSE-WAIT`; the core-side server observed the UE through the Kubernetes pod network and exited early. A cross-host test to the prepared RAN node kept both TCP control and UDP data active for the full measurement, completed with return code 0 on both sides, and delivered approximately the requested bitrate with zero packet loss.

That result established the external-peer requirement implemented by this change. A fresh capacity calibration against the external peer is still required before new load50/load80/load95 campaign evidence is accepted.
