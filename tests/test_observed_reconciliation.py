from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.observed import (
    Observation,
    ObservedState,
    reconcile_observation_sets,
    select_authoritative_observation,
)
from synthran.workspace.observed_store import load_observed_state, save_observed_state
from synthran.workspace.reconciliation import derive_lifecycle, plan_reconciliation
from synthran.workspace.registry import WorkspaceRegistry
from synthran.workspace.store import initialize_workspace


UTC = timezone.utc
NOW = datetime(2026, 8, 17, 19, 0, tzinfo=UTC)
EXP = "sran-20260817-001"


def live(
    dimension: str,
    state: str = "ready",
    *,
    source: str = "provider",
    ownership: str = "operator",
    minutes: int = 10,
    facts: dict[str, object] | None = None,
) -> Observation:
    return Observation(
        dimension=dimension,
        state=state,
        source=source,
        observed_at_utc="2026-08-17T19:00:00Z",
        fresh_until_utc=(NOW + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
        ownership=ownership,
        facts=facts or {},
    )


def historical(
    dimension: str,
    state: str,
    *,
    source: str,
    observed_at: str,
) -> Observation:
    return Observation(
        dimension=dimension,
        state=state,
        source=source,
        observed_at_utc=observed_at,
        ownership="synthran",
    )


def snapshot(*items: Observation) -> ObservedState:
    return ObservedState(
        experiment_id=EXP,
        collected_at_utc="2026-08-17T19:00:00Z",
        observations=tuple(items),
    )


def authority_ready() -> list[Observation]:
    return [
        live("controller"),
        live("project_access"),
        live("provider_experiment"),
    ]


def resources_ready() -> list[Observation]:
    return [
        live("reservation", ownership="operator"),
        live("allocation", ownership="operator"),
        live("preparation", ownership="synthran"),
    ]


def network_ready() -> list[Observation]:
    return [
        live("kubernetes", ownership="synthran"),
        live("core", ownership="synthran"),
        live("ran", ownership="synthran"),
        live("ue", ownership="synthran"),
        live("pdu", ownership="synthran", facts={"address": "12.1.1.2"}),
        live("upf", ownership="synthran"),
        live("radio", ownership="synthran"),
    ]


class ObservedStateTests(unittest.TestCase):
    def test_truth_hierarchy_prefers_fresh_provider_over_newer_lower_source(self) -> None:
        provider = Observation(
            dimension="allocation",
            state="ready",
            source="provider",
            observed_at_utc="2026-08-17T18:58:00Z",
            fresh_until_utc="2026-08-17T19:05:00Z",
            ownership="operator",
        )
        local = Observation(
            dimension="allocation",
            state="failed",
            source="observation",
            observed_at_utc="2026-08-17T18:59:00Z",
            fresh_until_utc="2026-08-17T19:05:00Z",
            ownership="operator",
        )
        self.assertEqual(
            select_authoritative_observation([local, provider], now=NOW), provider
        )

    def test_stale_provider_does_not_override_fresh_live_observation(self) -> None:
        provider = Observation(
            dimension="allocation",
            state="ready",
            source="provider",
            observed_at_utc="2026-08-17T18:00:00Z",
            fresh_until_utc="2026-08-17T18:10:00Z",
            ownership="operator",
        )
        direct = live("allocation", state="failed", source="observation")
        self.assertEqual(
            select_authoritative_observation([provider, direct], now=NOW), direct
        )

    def test_historical_fallback_respects_evidence_over_manifest_and_cache(self) -> None:
        evidence = historical(
            "path",
            "ready",
            source="evidence",
            observed_at="2026-08-17T18:00:00Z",
        )
        manifest = historical(
            "path",
            "failed",
            source="manifest",
            observed_at="2026-08-17T18:30:00Z",
        )
        cached = historical(
            "path",
            "failed",
            source="cache",
            observed_at="2026-08-17T18:50:00Z",
        )
        selected = select_authoritative_observation(
            [cached, manifest, evidence], now=NOW
        )
        self.assertEqual(selected, evidence)
        assert selected is not None
        self.assertFalse(selected.is_fresh(NOW))

    def test_live_observation_requires_freshness_boundary(self) -> None:
        with self.assertRaises(Exception):
            Observation(
                dimension="controller",
                state="ready",
                source="provider",
                observed_at_utc="2026-08-17T19:00:00Z",
            )

    def test_only_fresh_synthran_owned_live_fact_allows_automatic_mutation(self) -> None:
        owned = live("allocation", ownership="synthran")
        operator = live("allocation", ownership="operator")
        cached = historical(
            "allocation",
            "ready",
            source="cache",
            observed_at="2026-08-17T18:00:00Z",
        )
        self.assertTrue(owned.permits_automatic_mutation(NOW))
        self.assertFalse(operator.permits_automatic_mutation(NOW))
        self.assertFalse(cached.permits_automatic_mutation(NOW))

    def test_reconcile_sets_reduce_each_dimension_independently(self) -> None:
        result = reconcile_observation_sets(
            experiment_id=EXP,
            observations={
                "allocation": [
                    historical(
                        "allocation",
                        "failed",
                        source="manifest",
                        observed_at="2026-08-17T18:00:00Z",
                    ),
                    live("allocation", state="ready"),
                ],
                "path": [
                    historical(
                        "path",
                        "ready",
                        source="evidence",
                        observed_at="2026-08-17T18:30:00Z",
                    )
                ],
            },
            now=NOW,
        )
        self.assertEqual(result.state("allocation"), "ready")
        self.assertEqual(result.state("path"), "ready")
        assert result.get("path") is not None
        self.assertFalse(result.get("path").is_fresh(NOW))  # type: ignore[union-attr]

    def test_observed_snapshot_round_trips_in_experiment_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(root=root, profile="default", project="project", now=NOW)
            registry = WorkspaceRegistry(root)
            record = registry.create_experiment(
                profile="default",
                project="project",
                now=NOW,
            )
            state = ObservedState(
                experiment_id=record.experiment_id,
                collected_at_utc="2026-08-17T19:00:00Z",
                observations=(
                    live("pdu", facts={"address": "12.1.1.2"}),
                    live("allocation", facts={"node_count": 2}),
                ),
            )
            save_observed_state(root, state)
            loaded = load_observed_state(root, record.experiment_id)
            self.assertEqual(loaded.to_dict(), state.to_dict())
            self.assertEqual(loaded.get("pdu").facts["address"], "12.1.1.2")  # type: ignore[union-attr]


class ReconciliationTests(unittest.TestCase):
    def test_lifecycle_progression_uses_current_observations(self) -> None:
        desired = ExperimentDesiredState.recommended(intent="virtual-5g")
        self.assertEqual(
            derive_lifecycle(desired, snapshot(*authority_ready()), now=NOW),
            "CONFIGURED",
        )
        self.assertEqual(
            derive_lifecycle(
                desired,
                snapshot(*authority_ready(), live("reservation")),
                now=NOW,
            ),
            "RESERVED",
        )
        self.assertEqual(
            derive_lifecycle(
                desired,
                snapshot(
                    *authority_ready(),
                    live("reservation"),
                    live("allocation"),
                ),
                now=NOW,
            ),
            "ALLOCATED",
        )
        self.assertEqual(
            derive_lifecycle(
                desired,
                snapshot(
                    *authority_ready(),
                    live("reservation"),
                    live("allocation"),
                    live("preparation"),
                ),
                now=NOW,
            ),
            "PREPARED",
        )
        ready = snapshot(*authority_ready(), *resources_ready(), *network_ready())
        self.assertEqual(derive_lifecycle(desired, ready, now=NOW), "NETWORK_READY")
        proven = snapshot(
            *authority_ready(),
            *resources_ready(),
            *network_ready(),
            live("path"),
        )
        self.assertEqual(derive_lifecycle(desired, proven, now=NOW), "PATH_PROVEN")
        running = snapshot(
            *authority_ready(),
            *resources_ready(),
            *network_ready(),
            live("path"),
            live("experiment", facts={"running": True}),
        )
        self.assertEqual(
            derive_lifecycle(desired, running, now=NOW), "EXPERIMENT_RUNNING"
        )

    def test_unknown_reservation_is_inspected_not_mutated(self) -> None:
        desired = ExperimentDesiredState.recommended(intent="virtual-5g")
        report = plan_reconciliation(
            desired,
            snapshot(
                *authority_ready(),
                live("reservation", state="unknown", ownership="unknown"),
            ),
            now=NOW,
        )
        self.assertEqual([step.name for step in report.steps], ["inspect-reservation"])
        self.assertFalse(any(step.mutates for step in report.steps))

    def test_absent_reservation_produces_approved_mutation_step(self) -> None:
        desired = ExperimentDesiredState.recommended(intent="virtual-5g")
        report = plan_reconciliation(
            desired,
            snapshot(
                *authority_ready(),
                live("reservation", state="absent", ownership="unowned"),
            ),
            now=NOW,
        )
        self.assertEqual([step.name for step in report.steps], ["reserve"])
        self.assertEqual(report.steps[0].risk, "R2")
        self.assertTrue(report.steps[0].mutates)

    def test_unknown_or_foreign_allocation_ownership_blocks_mutation(self) -> None:
        desired = ExperimentDesiredState.recommended(intent="virtual-5g")
        report = plan_reconciliation(
            desired,
            snapshot(
                *authority_ready(),
                live("reservation", ownership="operator"),
                live("allocation", ownership="unknown"),
            ),
            now=NOW,
        )
        self.assertEqual(report.lifecycle, "BLOCKED")
        self.assertIn("allocation ownership is unknown", report.blocks)

    def test_incomplete_synthran_allocation_is_recoverable_but_operator_one_is_not(self) -> None:
        desired = ExperimentDesiredState.recommended(intent="virtual-5g")
        owned = plan_reconciliation(
            desired,
            snapshot(
                *authority_ready(),
                live("reservation", ownership="operator"),
                live("allocation", state="failed", ownership="synthran"),
            ),
            now=NOW,
        )
        self.assertIn("recover-allocation", [step.name for step in owned.steps])
        external = plan_reconciliation(
            desired,
            snapshot(
                *authority_ready(),
                live("reservation", ownership="operator"),
                live("allocation", state="failed", ownership="operator"),
            ),
            now=NOW,
        )
        self.assertEqual(external.lifecycle, "BLOCKED")
        self.assertIn("incomplete allocation is not SynthRAN-owned", external.blocks)

    def test_physical_radio_requires_current_r2lab_lease_before_prepare(self) -> None:
        desired = ExperimentDesiredState.recommended(intent="physical-5g")
        report = plan_reconciliation(
            desired,
            snapshot(
                *authority_ready(),
                live("reservation", ownership="operator"),
                live("allocation", ownership="operator"),
                live("r2lab_lease", state="absent", ownership="unowned"),
            ),
            now=NOW,
        )
        self.assertIn("obtain-r2lab-lease", [step.name for step in report.steps])
        self.assertFalse(
            next(step for step in report.steps if step.name == "obtain-r2lab-lease").mutates
        )

    def test_ready_resources_and_absent_network_produce_one_up_step(self) -> None:
        desired = ExperimentDesiredState.recommended(intent="virtual-5g")
        absent_network = [
            live(dimension, state="absent", ownership="unowned")
            for dimension in (
                "kubernetes",
                "core",
                "ran",
                "ue",
                "pdu",
                "upf",
                "radio",
            )
        ]
        report = plan_reconciliation(
            desired,
            snapshot(*authority_ready(), *resources_ready(), *absent_network),
            now=NOW,
        )
        self.assertEqual([step.name for step in report.steps], ["up"])
        self.assertEqual(report.steps[0].risk, "R2")

    def test_ready_network_requires_current_path_verification(self) -> None:
        desired = ExperimentDesiredState.recommended(intent="virtual-5g")
        report = plan_reconciliation(
            desired,
            snapshot(*authority_ready(), *resources_ready(), *network_ready()),
            now=NOW,
        )
        self.assertEqual([step.name for step in report.steps], ["verify-path"])
        self.assertEqual(report.steps[0].risk, "R1")
        self.assertFalse(report.steps[0].mutates)

    def test_path_proven_has_no_reconciliation_step(self) -> None:
        desired = ExperimentDesiredState.recommended(intent="virtual-5g")
        report = plan_reconciliation(
            desired,
            snapshot(
                *authority_ready(),
                *resources_ready(),
                *network_ready(),
                live("path"),
            ),
            now=NOW,
        )
        self.assertEqual(report.lifecycle, "PATH_PROVEN")
        self.assertEqual(report.steps, ())
        self.assertEqual(report.blocks, ())


if __name__ == "__main__":
    unittest.main()
