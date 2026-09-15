#!/usr/bin/env python3
"""Receive an Experiment-2 paced UDP calibration flow and report delivery stats.

Pure Python/stdlib on purpose: the calibration must not depend on iperf or any
additional package being installed on the SOP nodes.

The receiver has two distinct timing phases:
1. wait for the first packet (startup timeout), then
2. keep receiving until the flow has been idle for a short drain interval.

This avoids truncating a run merely because SSH/kubectl startup consumed part
of a fixed wall-clock timeout before the sender began.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import socket
import struct
import time

HEADER = struct.Struct("!QQ")  # sequence number, sender monotonic timestamp (ns)


def _default_bind_address() -> str:
    """Resolve the IPv4 address selected by the host's default route.

    Experiment 2 already resolves the broker endpoint from the broker host's
    default-route source address.  Using the same routing decision here keeps
    the receiver reachable without exposing the calibration socket on every
    host interface.
    """

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect performs local route selection without sending a packet.
        probe.connect(("1.1.1.1", 9))
        address = probe.getsockname()[0]
    except OSError as error:
        raise SystemExit(
            f"could not resolve a routed IPv4 address for the UDP receiver: {error}"
        ) from error
    finally:
        probe.close()
    return address


def _validated_bind_address(value: str | None) -> str:
    candidate = value or _default_bind_address()
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError as error:
        raise SystemExit(f"UDP receiver bind address must be an IPv4 address: {candidate}") from error
    if address.version != 4:
        raise SystemExit("UDP receiver requires an IPv4 bind address")
    if address.is_unspecified:
        raise SystemExit("refusing to bind the UDP calibration receiver to all interfaces")
    return str(address)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bind",
        default=None,
        help="local IPv4 address to bind; defaults to the default-route source address",
    )
    parser.add_argument("--port", type=int, default=39001)
    parser.add_argument("--startup-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--idle-timeout-seconds", type=float, default=2.0)
    # Backward-compatible alias used by the first pilot command.  It now means
    # only "time allowed for the first packet to arrive", not total run time.
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument("--rcvbuf-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--report-ready", action="store_true")
    args = parser.parse_args()

    startup_timeout_s = (
        args.timeout_seconds
        if args.timeout_seconds is not None
        else args.startup_timeout_seconds
    )
    if not math.isfinite(startup_timeout_s) or startup_timeout_s <= 0:
        raise SystemExit("startup timeout must be > 0")
    if not math.isfinite(args.idle_timeout_seconds) or args.idle_timeout_seconds <= 0:
        raise SystemExit("idle timeout must be > 0")
    if args.rcvbuf_bytes <= 0:
        raise SystemExit("--rcvbuf-bytes must be > 0")

    bind_address = _validated_bind_address(args.bind)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, args.rcvbuf_bytes)
    sock.bind((bind_address, args.port))
    sock.settimeout(0.25)
    if args.report_ready:
        print(json.dumps({"event": "receiver_ready", "bind": bind_address, "port": args.port}), flush=True)

    receiver_start_ns = time.monotonic_ns()
    first_rx_ns: int | None = None
    last_rx_ns: int | None = None
    last_rx_monotonic: float | None = None
    first_seq: int | None = None
    last_seq: int | None = None
    packets = 0
    payload_bytes = 0
    out_of_order = 0
    duplicates = 0
    seen: set[int] = set()
    startup_deadline = time.monotonic() + startup_timeout_s

    while True:
        now = time.monotonic()
        if first_rx_ns is None:
            if now >= startup_deadline:
                break
        elif last_rx_monotonic is not None:
            if now - last_rx_monotonic >= args.idle_timeout_seconds:
                break

        try:
            data, _peer = sock.recvfrom(65535)
        except socket.timeout:
            continue

        if len(data) < HEADER.size:
            continue

        seq, _send_ns = HEADER.unpack_from(data)
        now_ns = time.monotonic_ns()
        last_rx_monotonic = time.monotonic()
        if first_rx_ns is None:
            first_rx_ns = now_ns
            first_seq = seq
        last_rx_ns = now_ns

        if seq in seen:
            duplicates += 1
            continue
        if last_seq is not None and seq < last_seq:
            out_of_order += 1
        seen.add(seq)
        last_seq = seq if last_seq is None else max(last_seq, seq)
        packets += 1
        payload_bytes += len(data)

    receiver_end_ns = time.monotonic_ns()

    duration_s = 0.0
    if first_rx_ns is not None and last_rx_ns is not None and last_rx_ns >= first_rx_ns:
        duration_s = max((last_rx_ns - first_rx_ns) / 1e9, 1e-9)

    expected = 0
    if first_seq is not None and last_seq is not None and last_seq >= first_seq:
        expected = last_seq - first_seq + 1
    lost_within_observed_span = max(expected - packets, 0)

    result = {
        "bind": bind_address,
        "port": args.port,
        "startup_timeout_seconds": startup_timeout_s,
        "idle_timeout_seconds": args.idle_timeout_seconds,
        "receiver_wall_seconds": (receiver_end_ns - receiver_start_ns) / 1e9,
        "packets_received": packets,
        "payload_bytes_received": payload_bytes,
        "first_sequence": first_seq,
        "last_sequence": last_seq,
        "sequence_span_packets": expected,
        "sequence_loss_packets_within_observed_span": lost_within_observed_span,
        "sequence_loss_fraction_within_observed_span": (
            lost_within_observed_span / expected if expected else None
        ),
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "receive_span_seconds": duration_s,
        "socket_receive_buffer_bytes": sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF),
        "received_payload_mbps": (
            payload_bytes * 8 / duration_s / 1e6 if duration_s else 0.0
        ),
    }
    sock.close()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
