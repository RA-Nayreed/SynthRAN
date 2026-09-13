#!/usr/bin/env python3
"""Send a precisely paced UDP calibration flow for Experiment 2.

The requested rate is application-payload Mbps.  The sender binds to the chosen
5G UE address so existing source-policy routing forces the flow through that UE
tunnel.  No third-party packages are required.
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import time

HEADER = struct.Struct("!QQ")  # sequence number, sender monotonic timestamp (ns)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True)
    parser.add_argument("--port", type=int, default=39001)
    parser.add_argument("--bind-address", required=True)
    parser.add_argument("--rate-mbps", type=float, required=True)
    parser.add_argument("--duration-seconds", type=float, default=10.0)
    parser.add_argument("--packet-bytes", type=int, default=1200)
    parser.add_argument("--sndbuf-bytes", type=int, default=8 * 1024 * 1024)
    args = parser.parse_args()

    if args.rate_mbps <= 0:
        raise SystemExit("--rate-mbps must be > 0")
    if args.duration_seconds <= 0:
        raise SystemExit("--duration-seconds must be > 0")
    if args.packet_bytes < HEADER.size:
        raise SystemExit(f"--packet-bytes must be >= {HEADER.size}")

    destination = socket.gethostbyname(args.destination)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, args.sndbuf_bytes)
    sock.bind((args.bind_address, 0))

    payload = bytearray(args.packet_bytes)
    bits_per_packet = args.packet_bytes * 8
    interval_ns = int(bits_per_packet / (args.rate_mbps * 1e6) * 1e9)
    interval_ns = max(interval_ns, 1)

    start_ns = time.monotonic_ns()
    end_ns = start_ns + int(args.duration_seconds * 1e9)
    next_send_ns = start_ns
    seq = 0
    bytes_sent = 0
    send_errors = 0

    while True:
        now_ns = time.monotonic_ns()
        if now_ns >= end_ns:
            break
        if now_ns < next_send_ns:
            remaining_ns = next_send_ns - now_ns
            if remaining_ns > 200_000:
                time.sleep((remaining_ns - 100_000) / 1e9)
            continue

        HEADER.pack_into(payload, 0, seq, now_ns)
        try:
            sent = sock.sendto(payload, (destination, args.port))
            bytes_sent += sent
        except OSError:
            send_errors += 1
        seq += 1
        next_send_ns = start_ns + seq * interval_ns

    finish_ns = time.monotonic_ns()
    actual_duration_s = max((finish_ns - start_ns) / 1e9, 1e-9)
    result = {
        "destination": destination,
        "port": args.port,
        "bind_address": args.bind_address,
        "requested_payload_mbps": args.rate_mbps,
        "packet_bytes": args.packet_bytes,
        "packets_attempted": seq,
        "send_errors": send_errors,
        "payload_bytes_sent": bytes_sent,
        "duration_seconds": actual_duration_s,
        "actual_payload_mbps": bytes_sent * 8 / actual_duration_s / 1e6,
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
