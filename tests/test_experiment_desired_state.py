from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.workspace.desired import (
    CoreDesiredState,
    DnnDesiredState,
    ExperimentDesiredState,
    MultusDesiredState,
    PlacementDesiredState,
    PlmnDesiredState,
    RadioDesiredState,
    RanDesiredState,
    RicDesiredState,
    SliceDesiredState,
    UeDesiredState,
)
from synthran.workspace.desired_store import (
    desired_state_path,
    load_desired_state,
    save_desired_state,
)
from synthran.workspace.experiment_service import create_desired_experiment
from synthran.workspace.model import WorkspaceError
from synthran.workspace.registry import WorkspaceRegistry
from synthran.workspace.store import (
    initialize_workspace,
    load_active_experiment_id,
    load_experiment_record,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 17, 19, 0, tzinfo=UTC)


class DesiredStateTests(unittest.TestCase):
    def test_recommended_virtual_and_physical_profiles_choose_radio_capability(self) -> None:
        virtual = ExperimentDesiredState.recommended(intent="virtual-5g")
        physical = ExperimentDesiredState.recommended(intent="physical-5g")
        self.assertEqual(virtual.radio.mode, "virtual")
        self.assertEqual(virtual.radio.backend, "rfsim")
        self.assertEqual(physical.radio.mode, "physical")
        self.assertEqual(physical.radio.backend, "r2lab")
        self.assertEqual(physical.radio.hardware, "automatic")

    def test_full_5g_configuration_round_trips_without_runtime_observations(self) -> None:
        desired = ExperimentDesiredState(
            intent="open-ran",
            core=CoreDesiredState(
                implementation="oai",
                namespace="core",
                nrf_address_policy="static",
                nrf_address="10.10.10.20",
            ),
            ran=RanDesiredState(
                implementation="oai",
                namespace="ran",
                architecture="cu-cp-up-du",
                gnb_id=0xE01,
                f1_enabled=True,
                e1_enabled=True,
                du_enabled=True,
            ),
            ue=UeDesiredState(implementation="oai", namespace="ran", count=2),
            radio=RadioDesiredState(
                mode="physical",
                backend="r2lab",
                hardware="n300",
            ),
            plmn=PlmnDesiredState(mcc="001", mnc="01", tac=1),
            dnns=(
                DnnDesiredState(
                    name="oai",
                    pdu_session_type="ipv4",
                    ipv4_subnet="12.1.1.0/24",
                ),
                DnnDesiredState(
                    name="ims",
                    pdu_session_type="ipv4v6",
                    ipv4_subnet="14.1.1.0/24",
                    ipv6_subnet="2001:db8:14::/64",
                ),
            ),
            slices=(
                SliceDesiredState(
                    sst=1,
                    dnn="oai",
                    five_qi=5,
                    ambr_ul_bps=200_000_000,
                    ambr_dl_bps=400_000_000,
                    plmn_mcc="001",
                    plmn_mnc="01",
                ),
                SliceDesiredState(
                    sst=1,
                    sd="FFFFFF",
                    dnn="ims",
                    five_qi=2,
                    ambr_ul_bps=100_000_000,
                    ambr_dl_bps=200_000_000,
                    plmn_mcc="001",
                    plmn_mnc="01",
                ),
            ),
            multus=MultusDesiredState(
                enabled=True,
                network="f1-network",
                host_interface="br0",
            ),
            ric=RicDesiredState(enabled=True),
            placement=PlacementDesiredState(
                mode="manual",
                deployment_node="standard-2-1",
                core_node="sopnode-f2",
                ran_node="sopnode-f3",
                extra_resources=("r2lab",),
            ),
        )
        loaded = ExperimentDesiredState.from_dict(desired.to_dict())
        self.assertEqual(loaded, desired)
        serialized = json.dumps(desired.to_dict())
        for runtime_only in (
            "pdu_address",
            "pod_ip",
            "allocation_id",
            "reservation_id",
            "lease_id",
        ):
            self.assertNotIn(runtime_only, serialized)

    def test_discovered_service_address_cannot_be_frozen_into_desired_state(self) -> None:
        with self.assertRaises(WorkspaceError):
            CoreDesiredState(
                nrf_address_policy="discover",
                nrf_address="10.0.0.1",
            )

    def test_split_ran_constraints_are_validated(self) -> None:
        with self.assertRaises(WorkspaceError):
            RanDesiredState(
                architecture="cu-du",
                f1_enabled=False,
                du_enabled=True,
            )
        with self.assertRaises(WorkspaceError):
            RanDesiredState(
                architecture="cu-cp-up-du",
                f1_enabled=True,
                e1_enabled=False,
            )

    def test_dnn_slice_and_placement_references_are_validated(self) -> None:
        with self.assertRaises(WorkspaceError):
            DnnDesiredState(
                name="bad",
                pdu_session_type="ipv4",
                ipv4_subnet="12.1.1.1/24",
            )
        with self.assertRaises(WorkspaceError):
            ExperimentDesiredState(
                dnns=(
                    DnnDesiredState(
                        name="internet",
                        pdu_session_type="ipv4",
                        ipv4_subnet="12.1.1.0/24",
                    ),
                ),
                slices=(SliceDesiredState(sst=1, dnn="missing"),),
            )
        with self.assertRaises(WorkspaceError):
            PlacementDesiredState(
                mode="automatic",
                core_node="sopnode-f2",
            )

    def test_deserializer_rejects_string_booleans(self) -> None:
        value = ExperimentDesiredState().to_dict()
        core = value["core"]
        assert isinstance(core, dict)
        core["enabled"] = "false"
        with self.assertRaises(WorkspaceError):
            ExperimentDesiredState.from_dict(value)

    def test_desired_state_is_persisted_inside_experiment_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(
                root=root,
                profile="default",
                project="project",
                now=NOW,
            )
            registry = WorkspaceRegistry(root)
            desired = ExperimentDesiredState.recommended(intent="physical-5g")
            record = create_desired_experiment(
                registry,
                profile="default",
                project="project",
                desired=desired,
                label="physical testbed",
                slices_experiment="provider-exp-01",
                now=NOW,
            )
            self.assertEqual(record.experiment_id, "sran-20260817-001")
            self.assertEqual(record.network_intent, "physical-5g")
            self.assertEqual(record.radio_mode, "physical")
            self.assertEqual(load_desired_state(root, record.experiment_id), desired)
            self.assertEqual(load_active_experiment_id(root), record.experiment_id)
            self.assertTrue(desired_state_path(root, record.experiment_id).is_file())
            self.assertEqual(
                load_experiment_record(root, record.experiment_id),
                record,
            )

    def test_desired_state_replacement_must_be_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(root=root, profile="default", project="project", now=NOW)
            registry = WorkspaceRegistry(root)
            record = registry.create_experiment(
                profile="default",
                project="project",
                network_intent="virtual-5g",
                radio_mode="virtual",
                now=NOW,
            )
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            save_desired_state(root, record.experiment_id, desired)
            with self.assertRaises(WorkspaceError):
                save_desired_state(root, record.experiment_id, desired)
            save_desired_state(root, record.experiment_id, desired, replace=True)

    def test_failed_detailed_persistence_consumes_experiment_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(root=root, profile="default", project="project", now=NOW)
            registry = WorkspaceRegistry(root)
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            with patch(
                "synthran.workspace.experiment_service.save_desired_state",
                side_effect=OSError("disk failure"),
            ):
                with self.assertRaises(WorkspaceError):
                    create_desired_experiment(
                        registry,
                        profile="default",
                        project="project",
                        desired=desired,
                        now=NOW,
                    )
            next_record = create_desired_experiment(
                registry,
                profile="default",
                project="project",
                desired=desired,
                now=NOW,
            )
            self.assertEqual(next_record.experiment_id, "sran-20260817-002")


if __name__ == "__main__":
    unittest.main()
