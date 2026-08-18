from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import unittest

from synthran.resources.slices_inventory import (
    InventoryCommandResult,
    SlicesInventoryError,
    read_slices_compute_snapshot,
)
from synthran.workspace.model import format_utc


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def reservation(
    *,
    owner: str,
    nodes: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, object]:
    return {
        "id": 7000000001,
        "owner": owner,
        "nodes": nodes,
        "start_date": format_utc(start),
        "end_date": format_utc(end),
    }


class InventoryRunner:
    def __init__(self, *, reservations=None, allocations=None, fail: str | None = None):
        self.reservations = [] if reservations is None else reservations
        self.allocations = [] if allocations is None else allocations
        self.fail = fail
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command, _timeout):
        argv = tuple(command)
        self.calls.append(argv)
        if self.fail == "calendar" and argv[:3] == ("pos", "calendar", "list"):
            return InventoryCommandResult(2, "")
        if self.fail == "allocations" and argv[:3] == ("pos", "allocations", "list"):
            return InventoryCommandResult(2, "")
        if argv == ("pos", "calendar", "list", "--json"):
            return InventoryCommandResult(0, json.dumps(self.reservations))
        if argv == ("pos", "allocations", "list", "--json"):
            return InventoryCommandResult(0, json.dumps(self.allocations))
        raise AssertionError(f"unexpected command: {argv}")


def states(snapshot):
    return {
        item.resource_id: (item.availability, item.ownership)
        for item in snapshot.resources
    }


class SlicesInventoryTests(unittest.TestCase):
    def test_free_reviewed_nodes_are_available_and_unowned(self) -> None:
        runner = InventoryRunner()
        snapshot = read_slices_compute_snapshot(
            operator="operator",
            runner=runner,
            now=NOW,
        )
        self.assertTrue(snapshot.complete)
        self.assertEqual("slices", snapshot.provider)
        self.assertEqual(
            {
                "sopnode-f1": ("available", "unowned"),
                "sopnode-f2": ("available", "unowned"),
                "sopnode-f3": ("available", "unowned"),
                "sopnode-w3": ("available", "unowned"),
            },
            states(snapshot),
        )
        self.assertEqual(
            [
                ("pos", "calendar", "list", "--json"),
                ("pos", "allocations", "list", "--json"),
            ],
            runner.calls,
        )

    def test_active_operator_reservation_is_reusable_but_foreign_is_unsafe(self) -> None:
        runner = InventoryRunner(
            reservations=[
                reservation(
                    owner="operator",
                    nodes=["sopnode-f2"],
                    start=NOW - timedelta(minutes=10),
                    end=NOW + timedelta(minutes=20),
                ),
                reservation(
                    owner="other-user",
                    nodes=["sopnode-f3"],
                    start=NOW - timedelta(minutes=5),
                    end=NOW + timedelta(minutes=15),
                ),
            ]
        )
        snapshot = read_slices_compute_snapshot(
            operator="operator",
            runner=runner,
            now=NOW,
        )
        observed = states(snapshot)
        self.assertEqual(("available", "operator"), observed["sopnode-f2"])
        self.assertEqual(("unavailable", "other"), observed["sopnode-f3"])

    def test_allocations_override_free_state_and_preserve_safe_ownership(self) -> None:
        own_reservation = reservation(
            owner="operator",
            nodes=["sopnode-f2"],
            start=NOW - timedelta(minutes=10),
            end=NOW + timedelta(minutes=20),
        )
        runner = InventoryRunner(
            reservations=[own_reservation],
            allocations=[
                {"id": "allocation-a", "owner": "operator", "nodes": ["sopnode-f2"]},
                {"id": "allocation-b", "owner": "other-user", "nodes": ["sopnode-f3"]},
            ],
        )
        snapshot = read_slices_compute_snapshot(
            operator="operator",
            runner=runner,
            now=NOW,
        )
        observed = states(snapshot)
        self.assertEqual(("allocated", "operator"), observed["sopnode-f2"])
        self.assertEqual(("allocated", "other"), observed["sopnode-f3"])

    def test_future_reservation_shortens_freshness_boundary(self) -> None:
        transition = NOW + timedelta(seconds=8)
        runner = InventoryRunner(
            reservations=[
                reservation(
                    owner="other-user",
                    nodes=["sopnode-f1"],
                    start=transition,
                    end=NOW + timedelta(minutes=20),
                )
            ]
        )
        snapshot = read_slices_compute_snapshot(
            operator="operator",
            runner=runner,
            now=NOW,
        )
        self.assertEqual(format_utc(transition), snapshot.fresh_until_utc)
        self.assertEqual(("available", "unowned"), states(snapshot)["sopnode-f1"])

    def test_overlapping_active_reservations_fail_closed(self) -> None:
        runner = InventoryRunner(
            reservations=[
                reservation(
                    owner="operator",
                    nodes=["sopnode-f2"],
                    start=NOW - timedelta(minutes=5),
                    end=NOW + timedelta(minutes=10),
                ),
                reservation(
                    owner="operator",
                    nodes=["sopnode-f2"],
                    start=NOW - timedelta(minutes=1),
                    end=NOW + timedelta(minutes=20),
                ),
            ]
        )
        with self.assertRaisesRegex(SlicesInventoryError, "overlapping"):
            read_slices_compute_snapshot(operator="operator", runner=runner, now=NOW)

    def test_duplicate_allocations_fail_closed(self) -> None:
        runner = InventoryRunner(
            allocations=[
                {"id": "a", "owner": "operator", "nodes": ["sopnode-f2"]},
                {"id": "b", "owner": "operator", "nodes": ["sopnode-f2"]},
            ]
        )
        with self.assertRaisesRegex(SlicesInventoryError, "multiple allocations"):
            read_slices_compute_snapshot(operator="operator", runner=runner, now=NOW)

    def test_conflicting_reservation_and_allocation_owners_fail_closed(self) -> None:
        runner = InventoryRunner(
            reservations=[
                reservation(
                    owner="operator",
                    nodes=["sopnode-f2"],
                    start=NOW - timedelta(minutes=5),
                    end=NOW + timedelta(minutes=10),
                )
            ],
            allocations=[
                {"id": "a", "owner": "other-user", "nodes": ["sopnode-f2"]}
            ],
        )
        with self.assertRaisesRegex(SlicesInventoryError, "conflicting"):
            read_slices_compute_snapshot(operator="operator", runner=runner, now=NOW)

    def test_provider_query_failure_and_malformed_json_fail_closed(self) -> None:
        with self.assertRaisesRegex(SlicesInventoryError, "reservation inventory failed"):
            read_slices_compute_snapshot(
                operator="operator",
                runner=InventoryRunner(fail="calendar"),
                now=NOW,
            )

        class BadRunner(InventoryRunner):
            def __call__(self, command, _timeout):
                argv = tuple(command)
                if argv == ("pos", "calendar", "list", "--json"):
                    return InventoryCommandResult(0, "not-json")
                return super().__call__(command, _timeout)

        with self.assertRaisesRegex(SlicesInventoryError, "did not return JSON"):
            read_slices_compute_snapshot(
                operator="operator",
                runner=BadRunner(),
                now=NOW,
            )


if __name__ == "__main__":
    unittest.main()
