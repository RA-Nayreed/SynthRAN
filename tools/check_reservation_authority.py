#!/usr/bin/env python3
"""No-hardware behavioral checks for SynthRAN's authoritative reservation layer."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import yaml

from synthran import reservation
from synthran.scenario import _normalize_reservation_policy

ROOT = Path(__file__).resolve().parents[1]


class CheckError(RuntimeError):
    pass


def completed(
    argv: list[str],
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


class FakeCommands:
    def __init__(self, handler: Callable[[list[str], str | None, int], subprocess.CompletedProcess[str]]):
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv, *, check=True, stdin=None):
        command = list(argv)
        self.calls.append({"argv": command, "stdin": stdin})
        result = self.handler(command, stdin, len(self.calls))
        if check and result.returncode:
            detail = reservation._output(result) or f"exit status {result.returncode}"
            raise reservation.ReservationError(
                f"command failed: {' '.join(command)}\n{detail}"
            )
        return result


def expect_error(func: Callable[[], Any], needle: str) -> str:
    try:
        func()
    except Exception as exc:
        message = str(exc)
        if needle not in message:
            raise CheckError(f"expected error containing {needle!r}, got: {message}") from exc
        return message
    raise CheckError(f"expected failure containing {needle!r}")


def _provider_checks() -> dict[str, Any]:
    old_run = reservation.run
    old_interval = os.environ.get("SYNTHRAN_PROVIDER_PREFIX_INTERVAL_SECONDS")
    os.environ["SYNTHRAN_PROVIDER_PREFIX_INTERVAL_SECONDS"] = "0"
    try:
        def existing_handler(argv, _stdin, _index):
            if argv[:3] == ["slices", "project", "use"]:
                return completed(argv)
            if argv[:3] == ["slices", "experiment", "show"]:
                return completed(argv, stdout="exists\n")
            if argv[:3] == ["post5g", "experiment", "prefix"]:
                return completed(
                    argv,
                    stdout=json.dumps(
                        {
                            "subnet": "192.0.2.0/24",
                            "lb": "192.0.2.10",
                            "expiration_time": "2026-09-16T04:00:00Z",
                        }
                    ),
                )
            raise CheckError(f"unexpected provider command: {argv}")

        existing = FakeCommands(existing_handler)
        reservation.run = existing
        evidence = reservation.provider_context(
            {"mode": "require-existing", "project": "post5g-beta", "experiment": "synthran-ci"}
        )
        if evidence["experiment_created"] is not False:
            raise CheckError("existing provider context was reported as created")
        if any(call["argv"][:3] == ["slices", "experiment", "create"] for call in existing.calls):
            raise CheckError("require-existing provider policy created an experiment")

        prefix_attempt = 0

        def create_handler(argv, _stdin, _index):
            nonlocal prefix_attempt
            if argv[:3] == ["slices", "project", "use"]:
                return completed(argv)
            if argv[:3] == ["slices", "experiment", "show"]:
                return completed(argv, 1, stderr="not found")
            if argv[:3] == ["slices", "experiment", "create"]:
                return completed(argv, stdout="created\n")
            if argv[:3] == ["post5g", "experiment", "prefix"]:
                prefix_attempt += 1
                if prefix_attempt == 1:
                    return completed(argv, stdout="{}")
                return completed(
                    argv,
                    stdout=json.dumps(
                        {
                            "subnet": "198.51.100.0/24",
                            "lb": "198.51.100.10",
                            "expiration_time": "2026-09-16T04:00:00Z",
                        }
                    ),
                )
            raise CheckError(f"unexpected provider command: {argv}")

        created = FakeCommands(create_handler)
        reservation.run = created
        evidence = reservation.provider_context(
            {
                "mode": "create",
                "project": "post5g-beta",
                "experiment": "synthran-ci-new",
                "experiment_duration": "4h",
            }
        )
        if evidence["experiment_created"] is not True or prefix_attempt != 2:
            raise CheckError("provider create/retry behavior changed")

        def failure_handler(argv, _stdin, _index):
            if argv[:3] == ["slices", "project", "use"]:
                return completed(argv)
            if argv[:3] == ["slices", "experiment", "show"]:
                return completed(argv, stdout="exists\n")
            if argv[:3] == ["post5g", "experiment", "prefix"]:
                return completed(argv, 7, stderr="provider unavailable")
            raise CheckError(f"unexpected provider command: {argv}")

        failed = FakeCommands(failure_handler)
        reservation.run = failed
        expect_error(
            lambda: reservation.provider_context(
                {
                    "mode": "require-existing",
                    "project": "post5g-beta",
                    "experiment": "synthran-ci",
                }
            ),
            "provider unavailable",
        )
        prefix_calls = [
            call for call in failed.calls if call["argv"][:3] == ["post5g", "experiment", "prefix"]
        ]
        if len(prefix_calls) != reservation.PROVIDER_PREFIX_ATTEMPTS_EXISTING:
            raise CheckError("provider failure did not use bounded retry count")

        return {
            "existing_context": "passed",
            "create_and_retry": "passed",
            "bounded_failure": "passed",
        }
    finally:
        reservation.run = old_run
        if old_interval is None:
            os.environ.pop("SYNTHRAN_PROVIDER_PREFIX_INTERVAL_SECONDS", None)
        else:
            os.environ["SYNTHRAN_PROVIDER_PREFIX_INTERVAL_SECONDS"] = old_interval


def _event(event_id: str, nodes: list[str], now: dt.datetime, minutes: int = 180) -> dict[str, Any]:
    return {
        "id": event_id,
        "owner": "ci-user",
        "nodes": nodes,
        "start_date": (now - dt.timedelta(minutes=5)).isoformat(),
        "end_date": (now + dt.timedelta(minutes=minutes)).isoformat(),
    }


def _calendar_checks() -> dict[str, Any]:
    old_run = reservation.run
    now = dt.datetime(2026, 9, 16, 0, 0, tzinfo=dt.timezone.utc)
    selected = ["sopnode-f2", "sopnode-f3"]
    try:
        list_count = 0

        def create_handler(argv, _stdin, _index):
            nonlocal list_count
            if argv == ["pos", "calendar", "list", "--json"]:
                list_count += 1
                rows = [] if list_count == 1 else [_event("42", selected, now)]
                return completed(argv, stdout=json.dumps(rows))
            if argv[:3] == ["pos", "calendar", "create"]:
                if argv[-2:] != selected:
                    raise CheckError(f"calendar create remapped selected nodes: {argv}")
                return completed(argv, stdout="42\n")
            raise CheckError(f"unexpected calendar command: {argv}")

        fake = FakeCommands(create_handler)
        reservation.run = fake
        record = reservation.acquire_calendar(
            {"mode": "create", "duration_minutes": 120},
            selected=selected,
            owner="ci-user",
            now=now,
        )
        if record["id"] != "42" or record["nodes"] != selected:
            raise CheckError("new POS reservation evidence changed selected identity")

        existing_rows = [_event("77", selected, now)]

        def existing_handler(argv, _stdin, _index):
            if argv == ["pos", "calendar", "list", "--json"]:
                return completed(argv, stdout=json.dumps(existing_rows))
            raise CheckError(f"require-existing attempted mutation: {argv}")

        existing = FakeCommands(existing_handler)
        reservation.run = existing
        record = reservation.acquire_calendar(
            {"mode": "require-existing", "duration_minutes": 120},
            selected=selected,
            owner="ci-user",
            now=now,
        )
        if record["status"] != "required-existing":
            raise CheckError("require-existing did not record its policy")

        def unavailable_handler(argv, _stdin, _index):
            if argv == ["pos", "calendar", "list", "--json"]:
                return completed(argv, stdout="[]")
            if argv[:3] == ["pos", "calendar", "create"]:
                return completed(argv, 1, stderr="sopnode-f3 is busy")
            raise CheckError(f"unexpected unavailable command: {argv}")

        unavailable = FakeCommands(unavailable_handler)
        reservation.run = unavailable
        expect_error(
            lambda: reservation.acquire_calendar(
                {"mode": "create", "duration_minutes": 120},
                selected=selected,
                owner="ci-user",
                now=now,
            ),
            "sopnode-f3 is busy",
        )
        create_calls = [
            call["argv"] for call in unavailable.calls if call["argv"][:3] == ["pos", "calendar", "create"]
        ]
        if len(create_calls) != 1 or create_calls[0][-2:] != selected:
            raise CheckError("unavailable exact nodes triggered replacement/remapping")

        ambiguous_rows = [_event("80", selected, now), _event("81", selected, now)]

        def ambiguous_handler(argv, _stdin, _index):
            if argv == ["pos", "calendar", "list", "--json"]:
                return completed(argv, stdout=json.dumps(ambiguous_rows))
            raise CheckError(f"ambiguous coverage attempted mutation: {argv}")

        reservation.run = FakeCommands(ambiguous_handler)
        expect_error(
            lambda: reservation.acquire_calendar(
                {"mode": "require-existing", "duration_minutes": 120},
                selected=selected,
                owner="ci-user",
                now=now,
            ),
            "ambiguous authority",
        )

        return {
            "exact_create": "passed",
            "require_existing": "passed",
            "unavailable_no_remap": "passed",
            "ambiguous_fail_closed": "passed",
        }
    finally:
        reservation.run = old_run


def _preparation_checks() -> dict[str, Any]:
    old_run = reservation.run
    old_attempts = os.environ.get("SYNTHRAN_POS_READY_ATTEMPTS")
    old_interval = os.environ.get("SYNTHRAN_POS_READY_INTERVAL_SECONDS")
    os.environ["SYNTHRAN_POS_READY_ATTEMPTS"] = "1"
    os.environ["SYNTHRAN_POS_READY_INTERVAL_SECONDS"] = "0"
    try:
        node = "sopnode-f3"

        def fresh_handler(argv, _stdin, _index):
            if argv[:3] == ["pos", "allocations", "allocate"]:
                return completed(argv)
            if argv[:3] == ["pos", "nodes", "image"]:
                return completed(argv)
            if argv[:3] == ["pos", "nodes", "bootparameter"]:
                return completed(argv)
            if argv[:3] == ["pos", "nodes", "reset"]:
                return completed(argv)
            if argv[0] == "ssh":
                return completed(argv)
            raise CheckError(f"unexpected fresh command: {argv}")

        fresh = FakeCommands(fresh_handler)
        reservation.run = fresh
        evidence = reservation.prepare_hosts(
            {"host_preparation": "fresh", "image": "configured-image"},
            selected=[node],
            calendar={"status": "created"},
        )
        if evidence["nodes"][node]["image"] != "configured-image":
            raise CheckError("fresh preparation silently substituted the configured image")
        ordered = [call["argv"] for call in fresh.calls]
        expected_prefixes = [
            ["pos", "allocations", "allocate"],
            ["pos", "nodes", "image"],
            ["pos", "nodes", "bootparameter"],
            ["pos", "nodes", "reset"],
            ["ssh"],
        ]
        if [argv[: len(prefix)] for argv, prefix in zip(ordered, expected_prefixes)] != expected_prefixes:
            raise CheckError(f"fresh preparation ordering changed: {ordered}")
        boot = ordered[2]
        if "isolcpus=managed_irq,16-63" not in boot[-1] or "nosmt" not in boot[-1]:
            raise CheckError("fresh SOP preparation did not use the pinned N3xx boot parameters")

        allocate_count = 0

        def conflict_handler(argv, _stdin, _index):
            nonlocal allocate_count
            if argv[:3] == ["pos", "allocations", "allocate"]:
                allocate_count += 1
                if allocate_count == 1:
                    return completed(argv, 1, stdout="already allocated")
                return completed(argv)
            if argv[:4] == ["pos", "allocations", "free", "-k"]:
                return completed(argv)
            if argv[:3] in (
                ["pos", "nodes", "image"],
                ["pos", "nodes", "bootparameter"],
                ["pos", "nodes", "reset"],
            ):
                return completed(argv)
            if argv[0] == "ssh":
                return completed(argv)
            raise CheckError(f"unexpected conflict command: {argv}")

        conflict = FakeCommands(conflict_handler)
        reservation.run = conflict
        reservation.prepare_hosts(
            {"host_preparation": "fresh", "image": "configured-image"},
            selected=[node],
            calendar={"status": "required-existing"},
        )
        free_calls = [
            call for call in conflict.calls if call["argv"][:4] == ["pos", "allocations", "free", "-k"]
        ]
        if len(free_calls) != 1:
            raise CheckError("explicit fresh allocation conflict did not use exactly one guarded reclaim")

        preserve = FakeCommands(lambda argv, _stdin, _index: (_ for _ in ()).throw(CheckError(f"preserve mutated host: {argv}")))
        reservation.run = preserve
        evidence = reservation.prepare_hosts(
            {"host_preparation": "preserve", "image": "configured-image"},
            selected=[node],
            calendar={"status": "required-existing"},
        )
        if preserve.calls or evidence["mutations"] != []:
            raise CheckError("preserve mode performed a POS/SSH mutation")

        expect_error(
            lambda: reservation.prepare_hosts(
                {"host_preparation": "fresh", "image": "configured-image"},
                selected=[node],
                calendar={"status": "disabled"},
            ),
            "requires create or require-existing POS calendar authority",
        )

        return {
            "fresh_order": "passed",
            "configured_image_preserved": "passed",
            "allocation_conflict_guarded": "passed",
            "preserve_zero_mutation": "passed",
        }
    finally:
        reservation.run = old_run
        if old_attempts is None:
            os.environ.pop("SYNTHRAN_POS_READY_ATTEMPTS", None)
        else:
            os.environ["SYNTHRAN_POS_READY_ATTEMPTS"] = old_attempts
        if old_interval is None:
            os.environ.pop("SYNTHRAN_POS_READY_INTERVAL_SECONDS", None)
        else:
            os.environ["SYNTHRAN_POS_READY_INTERVAL_SECONDS"] = old_interval


def _policy_checks() -> dict[str, Any]:
    legacy = {
        "platform": "r2lab",
        "reservation": {"enabled": True, "duration_minutes": 120, "image": "keep-me", "node_pool": ["other"]},
        "r2lab_reservation": {"enabled": True, "duration_minutes": 90},
    }
    _normalize_reservation_policy(legacy)
    if legacy["reservation"]["mode"] != "create":
        raise CheckError("legacy reservation enabled did not canonicalize to create")
    if legacy["reservation"]["host_preparation"] != "fresh":
        raise CheckError("legacy reservation did not canonicalize host preparation")
    if "node_pool" in legacy["reservation"]:
        raise CheckError("retired node substitution pool survived canonicalization")
    if legacy["reservation"]["image"] != "keep-me":
        raise CheckError("canonicalization changed configured POS image")
    if legacy["r2lab_reservation"]["mode"] != "book":
        raise CheckError("legacy R2Lab enabled did not canonicalize to book")

    explicit = {
        "platform": "r2lab",
        "provider": {
            "mode": "require-existing",
            "project": "post5g-beta",
            "experiment": "synthran-ci",
        },
        "reservation": {
            "mode": "require-existing",
            "host_preparation": "preserve",
            "duration_minutes": 120,
            "image": "keep-me",
        },
        "r2lab_reservation": {"mode": "require-existing", "duration_minutes": 120},
    }
    _normalize_reservation_policy(explicit)
    if explicit["reservation"]["mode"] != "require-existing":
        raise CheckError("explicit POS policy changed")
    if explicit["reservation"]["host_preparation"] != "preserve":
        raise CheckError("explicit host-preparation policy changed")
    if explicit["r2lab_reservation"]["mode"] != "require-existing":
        raise CheckError("explicit R2Lab policy changed")

    invalid = {
        "platform": "r2lab",
        "reservation": {"mode": "disabled", "host_preparation": "fresh"},
    }
    expect_error(lambda: _normalize_reservation_policy(invalid), "fresh host preparation requires")

    return {
        "legacy_to_explicit": "passed",
        "explicit_independent_policies": "passed",
        "invalid_combination_rejected": "passed",
    }


def _load_r2lab_module():
    path = ROOT / "deployment/scripts/reserve_r2lab.py"
    spec = importlib.util.spec_from_file_location("synthran_check_reserve_r2lab", path)
    if spec is None or spec.loader is None:
        raise CheckError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _r2_args(tmp: Path, mode: str) -> list[str]:
    return [
        "--host", "faraday.inria.fr",
        "--username", "ci-slice",
        "--known-hosts", str(tmp / "known_hosts"),
        "--email", "ci@example.invalid",
        "--start", "2026-09-16T00:00",
        "--end", "2026-09-16T02:00",
        "--output", str(tmp / f"{mode}-lease.json"),
        "--log", str(tmp / f"{mode}-lease.log"),
        "--mode", mode,
    ]


def _r2lab_checks() -> dict[str, Any]:
    module = _load_r2lab_module()
    with tempfile.TemporaryDirectory(prefix="synthran-r2lab-check-") as tmp_value:
        tmp = Path(tmp_value)
        requested_start = 100
        requested_end = 200

        def evidence(leases):
            return json.dumps(
                {
                    "requested_start_epoch": requested_start,
                    "requested_end_epoch": requested_end,
                    "leases": leases,
                }
            )

        covering = {
            "id": 10,
            "slice_name": "ci-slice",
            "t_from": "2026-09-16T00:00:00+00:00",
            "t_until": "2026-09-16T02:00:00+00:00",
            "start_epoch": 90,
            "end_epoch": 210,
        }
        remote_calls: list[dict[str, Any]] = []

        def require_remote(_args, argv, *, stdin=None):
            remote_calls.append({"argv": list(argv), "stdin": stdin})
            if argv == ["true"]:
                return completed(argv)
            return completed(argv, stdout=evidence([covering]))

        module._remote = require_remote
        module._read_password = lambda: (_ for _ in ()).throw(CheckError("require-existing read a password"))
        if module.main(_r2_args(tmp, "require-existing")) != 0:
            raise CheckError("R2Lab require-existing did not succeed")
        record = json.loads((tmp / "require-existing-lease.json").read_text())
        if record["status"] != "reused" or record["policy_mode"] != "require-existing":
            raise CheckError("R2Lab require-existing evidence changed")

        short = dict(covering)
        short["id"] = 11
        short["end_epoch"] = 150
        query_count = 0
        remote_calls.clear()

        def extend_remote(_args, argv, *, stdin=None):
            nonlocal query_count
            remote_calls.append({"argv": list(argv), "stdin": stdin})
            if argv == ["true"]:
                return completed(argv)
            if argv and argv[0] == "python3" and module.EXTEND_CODE in argv:
                return completed(argv)
            query_count += 1
            return completed(argv, stdout=evidence([short] if query_count == 1 else [covering | {"id": 11}]))

        module._remote = extend_remote
        module._read_password = lambda: "top-secret"
        if module.main(_r2_args(tmp, "book")) != 0:
            raise CheckError("R2Lab extension did not succeed")
        extension_calls = [call for call in remote_calls if call["argv"] and module.EXTEND_CODE in call["argv"]]
        if len(extension_calls) != 1 or extension_calls[0]["stdin"] != "top-secret\n":
            raise CheckError("R2Lab extension credential was not carried only through stdin")
        if any("top-secret" in " ".join(map(str, call["argv"])) for call in remote_calls):
            raise CheckError("R2Lab password leaked into remote argv")

        remote_calls.clear()

        def denied_remote(_args, argv, *, stdin=None):
            remote_calls.append({"argv": list(argv), "stdin": stdin})
            if argv == ["true"]:
                return completed(argv)
            if argv and argv[0] == "python3" and module.BOOK_CODE in argv:
                return completed(argv, 3, stdout="booking denied by provider")
            return completed(argv, stdout=evidence([]))

        module._remote = denied_remote
        module._read_password = lambda: "top-secret"
        expect_error(lambda: module.main(_r2_args(tmp, "book")), "booking denied by provider")
        booking_calls = [call for call in remote_calls if call["argv"] and module.BOOK_CODE in call["argv"]]
        if len(booking_calls) != 1 or booking_calls[0]["stdin"] != "top-secret\n":
            raise CheckError("R2Lab booking credential transport changed")

        ambiguous = [covering, covering | {"id": 12}]

        def ambiguous_remote(_args, argv, *, stdin=None):
            if argv == ["true"]:
                return completed(argv)
            return completed(argv, stdout=evidence(ambiguous))

        module._remote = ambiguous_remote
        module._read_password = lambda: (_ for _ in ()).throw(CheckError("ambiguous lease read a password"))
        expect_error(lambda: module.main(_r2_args(tmp, "book")), "multiple owned R2Lab leases cover")

        called = False

        def disabled_remote(*_args, **_kwargs):
            nonlocal called
            called = True
            raise CheckError("disabled R2Lab policy touched the provider")

        module._remote = disabled_remote
        if module.main(_r2_args(tmp, "disabled")) != 0 or called:
            raise CheckError("disabled R2Lab policy performed a provider action")

    return {
        "existing_coverage": "passed",
        "extension_verified": "passed",
        "booking_denial_truthful": "passed",
        "ambiguous_fail_closed": "passed",
        "password_stdin_only": "passed",
        "disabled_zero_provider_action": "passed",
    }


def _no_input_and_identity_checks() -> dict[str, Any]:
    old_run = reservation.run
    old_stdin = sys.stdin
    old_user = os.environ.get("USER")

    class NoRead(io.StringIO):
        def read(self, *args, **kwargs):
            raise CheckError("reservation authority read stdin")

        def readline(self, *args, **kwargs):
            raise CheckError("reservation authority read stdin")

    try:
        os.environ["USER"] = "ci-user"
        sys.stdin = NoRead("")
        reservation.run = FakeCommands(
            lambda argv, _stdin, _index: (_ for _ in ()).throw(
                CheckError(f"disabled/preserve policy ran a command: {argv}")
            )
        )
        with tempfile.TemporaryDirectory(prefix="synthran-no-input-") as tmp_value:
            tmp = Path(tmp_value)
            config = tmp / "resolved.yml"
            run_dir = tmp / "result"
            config.write_text(
                yaml.safe_dump(
                    {
                        "deployment": {
                            "nodes": {
                                "core": "sopnode-f2",
                                "ran": "sopnode-f3",
                                "broker": "sopnode-f2",
                            },
                            "provider": {"mode": "disabled"},
                            "reservation": {
                                "mode": "disabled",
                                "host_preparation": "preserve",
                                "duration_minutes": 120,
                                "image": "unchanged",
                            },
                            "r2lab_reservation": {"mode": "disabled"},
                        }
                    },
                    sort_keys=False,
                )
            )
            evidence = reservation.execute(config, run_dir)
            if evidence["selected_nodes"] != {
                "core": "sopnode-f2",
                "ran": "sopnode-f3",
                "broker": "sopnode-f2",
            }:
                raise CheckError("reservation authority changed selected role identities")
            if evidence["status"] != "ready":
                raise CheckError("disabled/preserve no-input path did not complete")
            selection = json.loads((run_dir / "pos-selection.json").read_text())
            if selection["nodes"] != evidence["selected_nodes"]:
                raise CheckError("POS evidence changed selected node identities")

        source = (ROOT / "synthran/reservation.py").read_text(encoding="utf-8")
        legacy = (ROOT / "deployment/scripts/reserve_sop.py").read_text(encoding="utf-8")
        if "input(" in source or "input(" in legacy:
            raise CheckError("reservation path still contains interactive input()")

        return {
            "stdin_eof_safe": "passed",
            "selected_identity_immutable": "passed",
            "no_input_calls": "passed",
        }
    finally:
        reservation.run = old_run
        sys.stdin = old_stdin
        if old_user is None:
            os.environ.pop("USER", None)
        else:
            os.environ["USER"] = old_user


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = {
        "schema": "synthran/reservation-authority-check/v1",
        "policy": _policy_checks(),
        "provider": _provider_checks(),
        "pos_calendar": _calendar_checks(),
        "host_preparation": _preparation_checks(),
        "r2lab": _r2lab_checks(),
        "noninteractive": _no_input_and_identity_checks(),
        "result": "pass",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CheckError, reservation.ReservationError, OSError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(f"reservation-authority-check: {exc}") from exc
