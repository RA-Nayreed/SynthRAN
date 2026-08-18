from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import unittest

from synthran.control.live_operations import (
    LiveOperationError,
    _delete_run_owned_namespace,
    _reuse_only_preparation_runner,
)
from synthran.fiveg_ansible import InventoryHost, NetworkInventory
from synthran.workspace.access import ProbeResult


class WorkbenchLiveOperationGuardrailTests(unittest.TestCase):
    def test_prepare_runner_refuses_hidden_reservation_or_allocation_creation(self) -> None:
        with patch("synthran.control.live_operations.run_command") as delegate:
            with self.assertRaises(RuntimeError):
                _reuse_only_preparation_runner(
                    ("pos", "allocations", "allocate", "sopnode-f2", "sopnode-f3"),
                    None,
                    {},
                    60,
                )
            with self.assertRaises(RuntimeError):
                _reuse_only_preparation_runner(
                    ("pos", "calendar", "create", "-d", "120"),
                    None,
                    {},
                    60,
                )
            delegate.assert_not_called()

    def test_prepare_runner_delegates_non_resource_creation_commands(self) -> None:
        expected = ProbeResult(0, "ok")
        with patch(
            "synthran.control.live_operations.run_command",
            return_value=expected,
        ) as delegate:
            result = _reuse_only_preparation_runner(
                ("pos", "nodes", "image", "sopnode-f2", "--image", "example"),
                Path("/tmp"),
                {"PATH": "/usr/bin"},
                60,
            )
        self.assertEqual(result, expected)
        delegate.assert_called_once()

    def _inventory(self) -> NetworkInventory:
        variables = {
            "ansible_host": "192.0.2.10",
            "ansible_user": "root",
            "ansible_port": "22",
            "core": "open5gs",
            "ran": "srsran",
            "rru": "rfsim",
        }
        return NetworkInventory(
            path=Path("hosts.ini"),
            sha256="0" * 64,
            core_node=InventoryHost("sopnode-f2", variables),
            ran_node=InventoryHost("sopnode-f3", variables),
            all_vars=variables,
        )

    def test_teardown_namespace_query_fails_closed_on_transport_error(self) -> None:
        def runner(command, timeout):
            return ProbeResult(255, "", "transport failed")

        with self.assertRaises(LiveOperationError):
            _delete_run_owned_namespace(
                runner=runner,
                network_inventory=self._inventory(),
                run_id="op-000123",
            )

    def test_teardown_accepts_absent_namespace_without_delete(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(command, timeout):
            calls.append(tuple(command))
            return ProbeResult(0, "")

        _delete_run_owned_namespace(
            runner=runner,
            network_inventory=self._inventory(),
            run_id="op-000123",
        )
        self.assertEqual(len(calls), 1)
        self.assertIn("--ignore-not-found", calls[0][-1])

    def test_teardown_requires_exact_run_label_before_namespace_delete(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(command, timeout):
            calls.append(tuple(command))
            if len(calls) == 1:
                return ProbeResult(
                    0,
                    '{"metadata":{"labels":{"synthran.run/id":"another-run"}}}',
                )
            raise AssertionError("delete must not run for foreign namespace")

        with self.assertRaises(LiveOperationError):
            _delete_run_owned_namespace(
                runner=runner,
                network_inventory=self._inventory(),
                run_id="op-000123",
            )
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
