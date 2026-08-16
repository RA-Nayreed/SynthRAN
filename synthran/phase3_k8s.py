"""Run-scoped Kubernetes overlay for the Phase 3 MQTT path.

The accepted Phase 2 network is not redeployed.  Phase 3 temporarily adds one
Mosquitto sidecar to the existing run-owned srsUE Deployment so that the edge
bridge shares the network namespace containing ``tun_srsue1``.  Cleanup removes
the sidecar and recreates the original pod shape.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from typing import Any, Mapping

from synthran.dependencies import DependencyLock
from synthran.phase3_runtime import Phase3Error, Phase3Scenario, render_central_mosquitto_config, render_edge_mosquitto_config


EDGE_CONTAINER = "synthran-edge-mqtt"
EDGE_VOLUME = "synthran-phase3-edge-config"
CENTRAL_PORT = 18884
RUN_LABEL = "synthran.phase3/run"


def _mosquitto_image(lock: DependencyLock) -> str:
    containers = lock.raw.get("containers")
    entry = containers.get("mosquitto") if isinstance(containers, dict) else None
    if not isinstance(entry, dict):
        raise Phase3Error("dependency lock does not define the Mosquitto image")
    image = entry.get("image")
    digest = entry.get("digest")
    if not isinstance(image, str) or not isinstance(digest, str):
        raise Phase3Error("locked Mosquitto image is malformed")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise Phase3Error("locked Mosquitto image is not digest-addressed")
    return f"{image}@{digest}"


def _suffix(run_id: str) -> str:
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]


def names(scenario: Phase3Scenario) -> dict[str, str]:
    suffix = _suffix(scenario.run_id)
    return {
        "edge_config": f"synthran-p3-edge-{suffix}",
        "central_config": f"synthran-p3-central-{suffix}",
        "central_deployment": f"synthran-p3-central-{suffix}",
    }


def render_edge_patch(
    scenario: Phase3Scenario,
    *,
    lock: DependencyLock,
    core_address: str,
) -> Mapping[str, Any]:
    try:
        ipaddress.ip_address(core_address)
    except ValueError as exc:
        raise Phase3Error("core address must be a literal IP address") from exc
    resource_names = names(scenario)
    return {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {RUN_LABEL: scenario.run_id},
                },
                "spec": {
                    "volumes": [
                        {
                            "name": EDGE_VOLUME,
                            "configMap": {"name": resource_names["edge_config"]},
                        }
                    ],
                    "containers": [
                        {
                            "name": EDGE_CONTAINER,
                            "image": _mosquitto_image(lock),
                            "imagePullPolicy": "IfNotPresent",
                            "args": ["mosquitto", "-c", "/synthran/mosquitto.conf"],
                            "ports": [{"name": "mqtt-edge", "containerPort": 1883}],
                            "volumeMounts": [
                                {
                                    "name": EDGE_VOLUME,
                                    "mountPath": "/synthran",
                                    "readOnly": True,
                                }
                            ],
                            "readinessProbe": {
                                "tcpSocket": {"port": 1883},
                                "initialDelaySeconds": 2,
                                "periodSeconds": 2,
                            },
                        }
                    ],
                },
            }
        }
    }


def render_edge_cleanup_patch() -> Mapping[str, Any]:
    return {
        "spec": {
            "template": {
                "metadata": {"annotations": {RUN_LABEL: None}},
                "spec": {
                    "volumes": [{"name": EDGE_VOLUME, "$patch": "delete"}],
                    "containers": [{"name": EDGE_CONTAINER, "$patch": "delete"}],
                },
            }
        }
    }


def render_phase3_objects(
    scenario: Phase3Scenario,
    *,
    lock: DependencyLock,
    core_node: str,
    core_address: str,
) -> tuple[Mapping[str, Any], ...]:
    """Render ConfigMaps plus a host-network central broker Deployment."""

    try:
        ipaddress.ip_address(core_address)
    except ValueError as exc:
        raise Phase3Error("core address must be a literal IP address") from exc
    resource_names = names(scenario)
    labels = {
        "app.kubernetes.io/name": "synthran-phase3",
        "app.kubernetes.io/component": "mqtt",
        RUN_LABEL: scenario.run_id,
    }
    edge_config = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": resource_names["edge_config"],
            "namespace": "open5gs",
            "labels": labels,
        },
        "data": {
            "mosquitto.conf": render_edge_mosquitto_config(
                scenario,
                central_broker_address=core_address,
                central_broker_port=CENTRAL_PORT,
            )
        },
    }
    central_config = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": resource_names["central_config"],
            "namespace": "open5gs",
            "labels": labels,
        },
        "data": {
            "mosquitto.conf": render_central_mosquitto_config().replace(
                "listener 1883 0.0.0.0", f"listener {CENTRAL_PORT} 0.0.0.0"
            )
        },
    }
    central_deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": resource_names["central_deployment"],
            "namespace": "open5gs",
            "labels": labels,
        },
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {RUN_LABEL: scenario.run_id, "synthran.phase3/role": "central-mqtt"}},
            "template": {
                "metadata": {
                    "labels": {RUN_LABEL: scenario.run_id, "synthran.phase3/role": "central-mqtt"}
                },
                "spec": {
                    "hostNetwork": True,
                    "dnsPolicy": "ClusterFirstWithHostNet",
                    "nodeSelector": {"kubernetes.io/hostname": core_node},
                    "containers": [
                        {
                            "name": "central-mqtt",
                            "image": _mosquitto_image(lock),
                            "imagePullPolicy": "IfNotPresent",
                            "args": ["mosquitto", "-c", "/synthran/mosquitto.conf"],
                            "ports": [
                                {
                                    "name": "mqtt-central",
                                    "containerPort": CENTRAL_PORT,
                                    "hostPort": CENTRAL_PORT,
                                }
                            ],
                            "volumeMounts": [
                                {
                                    "name": "config",
                                    "mountPath": "/synthran",
                                    "readOnly": True,
                                }
                            ],
                            "readinessProbe": {
                                "tcpSocket": {"port": CENTRAL_PORT},
                                "initialDelaySeconds": 2,
                                "periodSeconds": 2,
                            },
                        }
                    ],
                    "volumes": [
                        {
                            "name": "config",
                            "configMap": {"name": resource_names["central_config"]},
                        }
                    ],
                },
            },
        },
    }
    return edge_config, central_config, central_deployment


def json_document(value: Mapping[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)
