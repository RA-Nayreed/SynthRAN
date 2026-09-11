#!/usr/bin/env python3
"""Reserve R2Lab without exposing credentials on argv and attest provider lease bounds."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import shlex
import subprocess
import sys


QUERY_CODE = r'''
import json, sys
from rhubarbe.book import Book
from rhubarbe.r2labapiproxy import iso_to_epoch
b = Book(verbose=False)
start = b.canonical_date(sys.argv[1])
end = b.canonical_date(sys.argv[2])
rows = []
for lease in b.leases(start, end):
    rows.append({
        "id": lease.get("id"),
        "slice_name": lease.get("slice_name"),
        "t_from": lease.get("t_from"),
        "t_until": lease.get("t_until"),
        "start_epoch": iso_to_epoch(lease["t_from"]),
        "end_epoch": iso_to_epoch(lease["t_until"]),
    })
print(json.dumps({
    "requested_start_epoch": start,
    "requested_end_epoch": end,
    "leases": rows,
}, separators=(",", ":")))
'''.strip()

BOOK_CODE = r'''
import sys
from rhubarbe.book import Book
email, slice_name, start_text, end_text = sys.argv[1:5]
password = sys.stdin.readline().rstrip("\r\n")
if not email or not password:
    raise SystemExit("R2Lab email/password are required to create a new lease")
b = Book(email=email, password=password, verbose=False)
start = b.canonical_date(start_text)
end = b.canonical_date(end_text)
raise SystemExit(0 if b.book(slice_name, start, end) else 3)
'''.strip()


def _ssh_base(args: argparse.Namespace) -> list[str]:
    command = ["ssh"]
    if args.host == "faraday.inria.fr":
        command += ["-F", "/dev/null"]
    command += [
        "-o",
        f"UserKnownHostsFile={args.known_hosts}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
    ]
    if args.identity_file:
        command += ["-i", args.identity_file, "-o", "IdentitiesOnly=yes"]
    return command


def _remote(
    args: argparse.Namespace,
    argv: list[str],
    *,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    target = f"{args.username}@{args.host}"
    command = _ssh_base(args) + [target, shlex.join(argv)]
    return subprocess.run(
        command,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def _query(args: argparse.Namespace) -> dict:
    result = _remote(
        args,
        ["python3", "-c", QUERY_CODE, args.start, args.end],
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"R2Lab provider lease query failed: {detail}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("R2Lab provider returned unreadable lease evidence") from error
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("leases"), list)
        or not isinstance(value.get("requested_start_epoch"), int)
        or not isinstance(value.get("requested_end_epoch"), int)
    ):
        raise RuntimeError("R2Lab provider lease response has an unexpected shape")
    return value


def _covering(leases: list[dict], username: str, start: int, end: int) -> list[dict]:
    return [
        lease
        for lease in leases
        if lease.get("slice_name") == username
        and int(lease.get("start_epoch", 0)) <= start
        and int(lease.get("end_epoch", 0)) >= end
    ]


def _owned_overlap(leases: list[dict], username: str) -> list[dict]:
    return [lease for lease in leases if lease.get("slice_name") == username]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--identity-file", default="")
    parser.add_argument("--known-hosts", required=True)
    parser.add_argument("--email", default="")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args(argv)

    args.known_hosts = str(Path(args.known_hosts).expanduser().resolve())
    Path(args.known_hosts).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.identity_file:
        identity = Path(args.identity_file).expanduser()
        if not identity.is_file():
            parser.error(f"R2Lab identity file not found: {identity}")
        args.identity_file = str(identity)

    # SSH authentication is tested without sending an API password.
    access = _remote(args, ["true"])
    if access.returncode:
        detail = (access.stderr or access.stdout).strip()
        raise SystemExit(f"R2Lab SSH authentication failed: {detail}")

    evidence = _query(args)
    start_epoch = evidence["requested_start_epoch"]
    end_epoch = evidence["requested_end_epoch"]
    if end_epoch <= start_epoch:
        parser.error("R2Lab end must be after start")
    leases = evidence["leases"]
    covering = _covering(leases, args.username, start_epoch, end_epoch)
    status = "reused"
    if len(covering) > 1:
        raise SystemExit("multiple owned R2Lab leases cover the requested interval")
    if not covering:
        overlaps = _owned_overlap(leases, args.username)
        if overlaps:
            latest = max(int(item.get("end_epoch", 0)) for item in overlaps)
            latest_text = dt.datetime.fromtimestamp(latest, dt.timezone.utc).isoformat()
            raise SystemExit(
                "owned R2Lab lease does not cover the requested deployment end; "
                f"provider coverage ends at {latest_text}. Refusing to create an overlapping extension."
            )
        password = sys.stdin.readline().rstrip("\r\n")
        booking = _remote(
            args,
            ["python3", "-c", BOOK_CODE, args.email, args.username, args.start, args.end],
            stdin=password + "\n",
        )
        password = ""
        if booking.returncode:
            detail = (booking.stderr or booking.stdout).strip()
            raise SystemExit(f"R2Lab reservation failed: {detail}")
        status = "booked"
        evidence = _query(args)
        start_epoch = evidence["requested_start_epoch"]
        end_epoch = evidence["requested_end_epoch"]
        leases = evidence["leases"]
        covering = _covering(leases, args.username, start_epoch, end_epoch)
        if len(covering) != 1:
            raise SystemExit(
                "R2Lab booking returned success but provider evidence does not prove the requested interval"
            )

    lease = covering[0]
    record = {
        "status": status,
        "requested": {
            "start": args.start,
            "end": args.end,
            "provider_start_epoch": start_epoch,
            "provider_end_epoch": end_epoch,
        },
        "provider_lease": lease,
        "verified_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.log.write_text(
        f"R2Lab lease {status}: id={lease.get('id')} slice={lease.get('slice_name')} "
        f"from={lease.get('t_from')} until={lease.get('t_until')}\n",
        encoding="utf-8",
    )
    print(
        f"R2Lab lease {status} and provider-verified through {lease.get('t_until')} "
        f"(lease id {lease.get('id')})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
