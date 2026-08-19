# Historical live research record — 2026-08-18

> [!NOTE]
> This file is an engineering-history record from before the accepted multi-seed campaign. **Do not use it as the current capability summary.** Current accepted evidence is in [`results.md`](results.md).

This record explains the diagnostic sequence that established the external measurement-peer and loaded-run validity rules used by the later accepted campaign.

## External-peer correction

Earlier research attempts exposed a same-host topology problem when the measurement target was placed on the 5G core host. A UE-bound flow could collapse into a Kubernetes/hairpin path and therefore fail to represent external user-plane egress.

The corrected topology became:

```text
UE PDU
-> tun_srsue1
-> srsRAN / Open5GS user plane
-> core egress / NAT
-> prepared RAN node as external peer
```

The 2026-08-18 accepted peer at that stage was:

```text
sopnode-f3 / 172.28.2.95
```

A fresh external-peer calibration under the then-current network epoch measured approximately 66.7 Mbps. That calibration and network run are now historical; the current accepted calibration is listed in [`results.md`](results.md).

## Transport-aware readiness

A 1 Mbps smoke run showed that ICMP-only pre-window readiness was the wrong gate for a loaded condition. The corrected rule proves the transport that defines the treatment:

1. exact target route through `tun_srsue1`;
2. run-owned external iperf3 listener;
3. UE client bound to the live PDU;
4. actual TCP control connection in `ESTABLISHED` state before the UDP measurement window opens.

`CLOSE-WAIT` is not accepted as equivalent readiness.

This rule is now part of the supported measurement-peer contract.

## High-rate single-flow diagnostic

One historical load80 pilot remained a useful **invalid diagnostic**. The base network and telemetry path stayed healthy, but the single high-rate iperf3 flow stalled and ended with a broken control channel before satisfying the treatment contract.

The follow-up kept the same aggregate load but split it over two UDP flows. The 50%, 80%, and 95% loaded pilots then completed their windows and passed the independent path/load/instrumentation checks.

That pilot evidence motivated the two-flow protocol used by the later blocked campaign. The historical failed run must not be interpreted as congestion-induced 5G-path failure.

## Why this file remains

Invalid and superseded experiments are not deleted or rewritten because they document how the measurement contract was hardened. They remain diagnostic evidence, not treatment observations.

The later accepted campaign supersedes this file for current scientific claims:

- current campaign: `campaign-20260819-06`;
- current network/calibration and measured results: [`results.md`](results.md);
- current protocol: [`experiment.md`](experiment.md);
- current peer invariant: [`research-measurement-peer.md`](research-measurement-peer.md).
