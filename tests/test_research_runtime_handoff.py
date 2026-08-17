from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from synthran.research.runtime import _measurement_runtime_handoff


class MeasurementRuntimeHandoffTests(unittest.TestCase):
    def test_handoff_reuses_reconciled_scenario_without_runtime_restart(self) -> None:
        scenario = SimpleNamespace(
            network_run_id="network-accepted",
            pdu_address="12.1.0.12",
        )
        inventory = object()

        with (
            patch(
                "synthran.research.runtime.base_runtime._discover_ue_pod",
                return_value="ue-pod",
            ) as discover,
            patch("synthran.research.runtime.reconcile_rfsim_runtime") as reconcile,
        ):
            ue_pod, pdu_address = _measurement_runtime_handoff(
                inventory,
                scenario,
            )

        self.assertEqual(ue_pod, "ue-pod")
        self.assertEqual(pdu_address, "12.1.0.12")
        discover.assert_called_once_with(inventory, "network-accepted")
        reconcile.assert_not_called()


if __name__ == "__main__":
    unittest.main()
