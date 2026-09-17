#!/usr/bin/env python3
"""Validate Sub 10 accepted-testbed and experiment-eligibility contracts."""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from synthran.acceptance import bind_prerequisite_evidence
from synthran.cluster_identity import selected_cluster_runtime
from synthran.deployment_identity import selected_source_pins, write_execution_manifest
from synthran.deployment_state import content_hash
from synthran.testbed_attachment import (
    AttachmentError,
    attach_active_deployment,
    prove_experiment_eligible,
)

ROOT = Path(__file__).resolve().parents[1]


def require_failure(action, message: str) -> None:
    try:
        action()
    except AttachmentError:
        return
    raise AssertionError(message)


def pod(name: str, labels: dict[str, str], container: str, image_id: str) -> dict:
    return {
        "name": name,
        "labels": labels,
        "phase": "Running",
        "ready": True,
        "containers": [
            {
                "kind": "container",
                "name": container,
                "configured_image": f"example/{container}:ci",
                "runtime_image_id": "containerd://" + image_id,
                "ready": True,
            }
        ],
    }


def stage_execution(private: Path, deployment: dict, result: Path) -> dict:
    staged = private / "ansible"
    shutil.copytree(ROOT / "deployment", staged)
    (staged / "reference").mkdir(parents=True)
    shutil.copyfile(
        ROOT / "third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json",
        staged / "reference/EXECUTION_REFERENCE.json",
    )
    return write_execution_manifest(deployment, staged, result / "execution-manifest.json")


def main() -> None:
    digest_a = "sha256:" + "a" * 64
    digest_b = "sha256:" + "b" * 64
    digest_c = "sha256:" + "c" * 64
    digest_d = "sha256:" + "d" * 64
    values_a = "1" * 64
    values_b = "2" * 64

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        private = root / "private"
        result = root / "deployment-result"
        private.mkdir()
        result.mkdir()
        (private / "inventory.yml").write_text("all: {}\n", encoding="utf-8")
        (private / "deployment-vars.yml").write_text("{}\n", encoding="utf-8")

        deployment = {
            "core": "open5gs",
            "ran": "srsran",
            "platform": "rfsim",
            "radio_unit": "rfsim",
            "network_profile": "ci",
            "network_profile_hash": "sha256:" + "9" * 64,
            "bridge_enabled": True,
            "nodes": {"core": "f2", "ran": "f3", "broker": "f2"},
            "topology": {"namespace": "open5gs"},
            "slices": [
                {
                    "name": "default",
                    "sst": "1",
                    "sd": "000001",
                    "dnn": "internet",
                    "ip_prefix": "12.1.1",
                }
            ],
            "ues": [
                {
                    "device": "uesim01",
                    "index": 1,
                    "imsi": "001010000000001",
                    "slice": "default",
                    "sst": "1",
                    "sd": "000001",
                    "dnn": "internet",
                    "address_cidr": "12.1.1.0/24",
                    "user_plane_target": "12.1.1.1",
                    "tunnel": {
                        "namespace": "open5gs",
                        "interface": "tun_srsue1",
                    },
                }
            ],
        }
        configuration_hash = content_hash(deployment)
        snapshot = {
            "schema_version": 3,
            "namespace": "open5gs",
            "cluster_attestation": {"configuration_hash": configuration_hash},
            "pods": [
                pod("open5gs-amf", {"nf": "amf"}, "amf", digest_a),
                pod(
                    "srsran-gnb",
                    {"app": "srsran", "component": "gnb"},
                    "gnb",
                    digest_b,
                ),
                pod(
                    "srsran-ue",
                    {"app": "srsran", "component": "ue"},
                    "ue",
                    digest_c,
                ),
                {
                    "name": "unrelated-debug",
                    "labels": {"app": "unrelated"},
                    "phase": "Pending",
                    "ready": False,
                    "containers": [
                        {
                            "kind": "container",
                            "name": "debug",
                            "configured_image": "example/debug:latest",
                            "runtime_image_id": "",
                            "ready": False,
                        }
                    ],
                },
            ],
            "helm_releases": [
                {
                    "name": "srsran-gnb",
                    "status": "deployed",
                    "chart": "srsran-gnb-0.1.0",
                    "app_version": "ci",
                    "values_sha256": values_a,
                },
                {
                    "name": "srsran-ue",
                    "status": "deployed",
                    "chart": "srsran-ue-0.1.0",
                    "app_version": "ci",
                    "values_sha256": values_b,
                },
                {
                    "name": "unrelated",
                    "status": "failed",
                    "chart": "unrelated-1.0.0",
                    "app_version": "ci",
                    "values_sha256": "0" * 64,
                },
            ],
        }
        cluster_runtime = selected_cluster_runtime(deployment, snapshot)

        execution = stage_execution(private, deployment, result)
        (result / "bootstrap-evidence.json").write_text(
            json.dumps({"host_preparation": "fresh", "nodes": [], "cluster_nodes": {}}),
            encoding="utf-8",
        )
        (result / "transport-evidence.json").write_text(
            json.dumps({"schema_version": 1, "deployment_hash": configuration_hash}),
            encoding="utf-8",
        )
        prerequisites = bind_prerequisite_evidence(result, configuration_hash)
        implementation = {
            "schema_version": 2,
            "execution_context": {
                "sha256": execution["sha256"],
                "file_count": execution["file_count"],
            },
            "reviewed_sources": selected_source_pins(deployment, result),
            "selected_runtime": {},
            "cluster_runtime": cluster_runtime,
        }
        deployment_hash = content_hash(
            {"deployment": deployment, "implementation": implementation}
        )
        implementation_hash = content_hash(implementation)
        now = datetime.now(timezone.utc).isoformat()

        identity = result / "accepted.json"
        evidence = result / "live-deployment-evidence.json"
        endpoint = root / "endpoint.json"
        identity_document = {
            "schema_version": 2,
            "acceptance_schema_version": 1,
            "status": "accepted-testbed",
            "configuration_hash": configuration_hash,
            "deployment_hash": deployment_hash,
            "implementation_identity_sha256": implementation_hash,
            "implementation": implementation,
            "prerequisite_evidence": prerequisites,
            "deployment": deployment,
            "accepted_at": now,
            "acceptance_evidence": {
                "observed_at": now,
                "implementation_identity_sha256": implementation_hash,
                "prerequisite_evidence": prerequisites,
            },
        }
        identity.write_text(json.dumps(identity_document), encoding="utf-8")

        binding = {
            "device": "uesim01",
            "index": 1,
            "imsi": "001010000000001",
            "slice": "default",
            "sst": "1",
            "sd": "000001",
            "dnn": "internet",
            "namespace": "open5gs",
            "interface": "tun_srsue1",
            "address": "12.1.1.2",
            "software_verified": True,
            "user_plane": {
                "verified": True,
                "method": "icmp_echo",
                "source_interface": "tun_srsue1",
                "source_address": "12.1.1.2",
                "target_address": "12.1.1.1",
                "observed_at": now,
            },
        }
        accepted_evidence = {
            "schema_version": 2,
            "configuration_hash": configuration_hash,
            "deployment_hash": deployment_hash,
            "implementation_identity_sha256": implementation_hash,
            "cluster_identity_verified": True,
            "bindings": [binding],
            "observed_at": now,
        }
        evidence.write_text(json.dumps(accepted_evidence), encoding="utf-8")
        endpoint.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "status": "accepted-testbed",
                    "configuration_hash": configuration_hash,
                    "deployment_hash": deployment_hash,
                    "run_id": "ci-deployment",
                    "identity_file": str(identity),
                    "evidence_file": str(evidence),
                    "private_execution_dir": str(private),
                    "result_dir": str(result),
                    "published_at": now,
                }
            ),
            encoding="utf-8",
        )

        requirements = {
            "core": "open5gs",
            "ran": ["srsran", "oai"],
            "platform": "rfsim",
            "radio_unit": "rfsim",
            "nodes": {"core": "f2", "ran": "f3"},
            "ue_devices": ["uesim01"],
            "exact_ue_devices": True,
            "ues": [
                {
                    "device": "uesim01",
                    "dnn": "internet",
                    "interface": "tun_srsue1",
                }
            ],
            "slices": [{"name": "default", "dnn": "internet"}],
        }
        attached = attach_active_deployment(requirements, endpoint_path=endpoint)
        assert attached["status"] == "accepted-testbed-attached", attached
        assert attached["experiment_eligible"] is False, attached
        assert attached["mode"] == "read_only", attached
        assert attached["deployment_hash"] == deployment_hash, attached

        require_failure(
            lambda: attach_active_deployment({"ran": "oai"}, endpoint_path=endpoint),
            "incompatible accepted deployment was not rejected",
        )

        bad_evidence = copy.deepcopy(accepted_evidence)
        bad_evidence["implementation_identity_sha256"] = "sha256:" + "0" * 64
        evidence.write_text(json.dumps(bad_evidence), encoding="utf-8")
        require_failure(
            lambda: attach_active_deployment(endpoint_path=endpoint),
            "wrong implementation evidence was accepted",
        )
        evidence.write_text(json.dumps(accepted_evidence), encoding="utf-8")

        staged_cfg = private / "ansible/ansible.cfg"
        staged_cfg_original = staged_cfg.read_text(encoding="utf-8")
        staged_cfg.write_text(staged_cfg_original + "\n# tampered\n", encoding="utf-8")
        require_failure(
            lambda: attach_active_deployment(endpoint_path=endpoint),
            "tampered retained execution context was accepted",
        )
        staged_cfg.write_text(staged_cfg_original, encoding="utf-8")

        bootstrap = result / "bootstrap-evidence.json"
        bootstrap_original = bootstrap.read_text(encoding="utf-8")
        bootstrap.write_text('{"tampered": true}\n', encoding="utf-8")
        require_failure(
            lambda: attach_active_deployment(endpoint_path=endpoint),
            "tampered predecessor evidence was accepted",
        )
        bootstrap.write_text(bootstrap_original, encoding="utf-8")

        unrelated_changed = copy.deepcopy(snapshot)
        unrelated_changed["pods"][3]["name"] = "unrelated-changed"
        unrelated_changed["helm_releases"][2]["status"] = "pending-install"
        assert selected_cluster_runtime(deployment, unrelated_changed) == cluster_runtime

        fresh_evidence = root / "experiment-eligibility-evidence.json"
        fresh_cluster = root / "experiment-eligibility-cluster.json"
        fresh_evidence.write_text(json.dumps(accepted_evidence), encoding="utf-8")
        fresh_cluster.write_text(json.dumps(unrelated_changed), encoding="utf-8")
        eligible = prove_experiment_eligible(
            fresh_evidence,
            requirements,
            endpoint_path=endpoint,
            max_age_seconds=120,
        )
        assert eligible["status"] == "experiment-eligible", eligible
        assert eligible["experiment_eligible"] is True, eligible

        drifted = copy.deepcopy(snapshot)
        drifted["pods"][1]["containers"][0]["runtime_image_id"] = (
            "containerd://" + digest_d
        )
        fresh_cluster.write_text(json.dumps(drifted), encoding="utf-8")
        require_failure(
            lambda: prove_experiment_eligible(
                fresh_evidence,
                requirements,
                endpoint_path=endpoint,
                max_age_seconds=120,
            ),
            "selected runtime image drift was not rejected",
        )

        fresh_cluster.write_text(json.dumps(snapshot), encoding="utf-8")
        stale = copy.deepcopy(accepted_evidence)
        stale["observed_at"] = "2000-01-01T00:00:00+00:00"
        fresh_evidence.write_text(json.dumps(stale), encoding="utf-8")
        require_failure(
            lambda: prove_experiment_eligible(
                fresh_evidence,
                requirements,
                endpoint_path=endpoint,
                max_age_seconds=120,
            ),
            "stale experiment eligibility evidence was accepted",
        )

    print("accepted-testbed and experiment-eligibility contracts OK")


if __name__ == "__main__":
    main()
