"""Message validation and response helpers for the SynthRAN control stream."""

from __future__ import annotations

from collections.abc import Mapping

from synthran.workspace.model import WorkspaceError


CONTROL_VERSION = 5
SUPPORTED_METHODS = frozenset(
    {
        "system.handshake",
        "setup.inspect",
        "workspace.initialize",
        "workspace.snapshot",
        "workspace.update_defaults",
        "experiment.create",
        "provider.experiments",
        "experiment.bind_provider",
        "operation.inspect",
        "operation.plan",
        "operation.read",
        "operation.approve",
        "operation.cancel",
    }
)
LOCAL_WRITE_METHODS = frozenset(
    {
        "workspace.initialize",
        "workspace.update_defaults",
        "experiment.create",
        "experiment.bind_provider",
        "operation.plan",
        "operation.approve",
        "operation.cancel",
    }
)
PROVIDER_READ_METHODS = frozenset(
    {
        "workspace.initialize",
        "provider.experiments",
        "experiment.bind_provider",
    }
)


def parse_request(value: object) -> tuple[str, str, Mapping[str, object]]:
    if not isinstance(value, Mapping):
        raise WorkspaceError("control request must be a JSON object")
    if value.get("v") != CONTROL_VERSION:
        raise WorkspaceError("control protocol version is unsupported")

    request_id = value.get("id")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
        raise WorkspaceError("control request id is malformed")

    method = value.get("method")
    if not isinstance(method, str) or not method or len(method) > 128:
        raise WorkspaceError("control method is malformed")

    params = value.get("params", {})
    if not isinstance(params, Mapping):
        raise WorkspaceError("control request params must be an object")

    return request_id, method, params


def success_response(request_id: str, result: Mapping[str, object]) -> dict[str, object]:
    return {
        "v": CONTROL_VERSION,
        "id": request_id,
        "ok": True,
        "result": dict(result),
    }


def error_response(
    request_id: str | None,
    *,
    code: str,
    message: str,
) -> dict[str, object]:
    return {
        "v": CONTROL_VERSION,
        "id": request_id,
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
