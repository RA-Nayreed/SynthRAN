from __future__ import annotations
import copy, re
from pathlib import Path
import yaml

from .profile_validation import (
    validate_network_profile,
    validate_ue_catalog,
    validate_ue_slice_assignments,
)

SUPPORTED_CORES = {"oai", "open5gs", "free5gc"}
SUPPORTED_RANS = {"oai", "srsran", "ueransim"}
SUPPORTED_PLATFORMS = {"rfsim", "r2lab"}
SUPPORTED_R2LAB_RADIOS = {"n300", "n320"}
_TRANSPORT_KEYS = {"mode", "interface", "mbim_session"}
_INSECURE_SSH = re.compile(
    r"(?:StrictHostKeyChecking\s*=\s*no|UserKnownHostsFile\s*=\s*/dev/null)", re.I
)
_SAFE_PROFILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def _network_profile_source(deployment: dict) -> Path:
    if deployment.get("network_profile_file"):
        return Path(deployment["network_profile_file"])
    name = str(deployment.get("network_profile", ""))
    return Path("deployment/group_vars/all") / f"network_profile_{name}.yaml"


def _ue_catalog_source(deployment: dict) -> Path:
    return Path(deployment.get("ue_catalog_file") or "deployment/group_vars/all/ue_catalog.yaml")


def _validate_ssh_policy(deployment: dict, host_vars: dict) -> None:
    for host, values in host_vars.items():
        if values is not None and not isinstance(values, dict):
            raise ValueError(f"deployment.host_vars.{host} must be a mapping")
        values = values or {}
        for key in ("ansible_ssh_common_args", "ansible_ssh_extra_args"):
            if _INSECURE_SSH.search(str(values.get(key, ""))):
                raise ValueError(
                    f"deployment.host_vars.{host}.{key} disables SSH server verification"
                )
        for key in ("ansible_host_key_checking", "ansible_ssh_host_key_checking"):
            if key in values and str(values[key]).strip().lower() in {
                "0",
                "false",
                "no",
                "off",
            }:
                raise ValueError(
                    f"deployment.host_vars.{host}.{key} cannot disable SSH server verification"
                )

    ansible_vars = deployment.get("ansible_vars", {})
    if ansible_vars is not None and not isinstance(ansible_vars, dict):
        raise ValueError("deployment.ansible_vars must be a mapping when provided")
    ansible_vars = ansible_vars or {}
    for key in ("ansible_ssh_common_args", "ansible_ssh_extra_args"):
        if _INSECURE_SSH.search(str(ansible_vars.get(key, ""))):
            raise ValueError(f"deployment.ansible_vars.{key} disables SSH server verification")
    for key in ("ansible_host_key_checking", "ansible_ssh_host_key_checking"):
        if key in ansible_vars and str(ansible_vars[key]).strip().lower() in {
            "0",
            "false",
            "no",
            "off",
        }:
            raise ValueError(
                f"deployment.ansible_vars.{key} cannot disable SSH server verification"
            )


def load_scenario(path: str | Path) -> dict:
    source = Path(path).resolve()
    with source.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError("scenario must be a mapping")
    if not isinstance(data.get("deployment"), dict):
        raise ValueError("scenario requires mapping: deployment")
    dep = data["deployment"]

    legacy = sorted(key for key in ("profile", "profile_file", "ue_profiles") if key in dep)
    if legacy:
        raise ValueError(
            "legacy deployment fields are no longer supported: "
            + ", ".join(legacy)
            + "; use network_profile and explicit ue_slices"
        )

    if dep.get("core") not in SUPPORTED_CORES:
        raise ValueError("unsupported core")
    if str(dep.get("ran", "")).lower() not in SUPPORTED_RANS:
        raise ValueError("unsupported RAN")
    if dep.get("platform") not in SUPPORTED_PLATFORMS:
        raise ValueError(
            "unsupported platform; supported platforms are: "
            + ", ".join(sorted(SUPPORTED_PLATFORMS))
        )
    if dep.get("platform") == "r2lab" and dep.get("ru") not in SUPPORTED_R2LAB_RADIOS:
        raise ValueError(
            "unsupported R2Lab radio; supported radios are: "
            + ", ".join(sorted(SUPPORTED_R2LAB_RADIOS))
        )
    if dep.get("radio") not in (None, {}):
        raise ValueError(
            "deployment.radio is not a supported effective configuration surface; "
            "use documented deployment fields/ansible_vars that are actually rendered"
        )

    if "r2lab_experiment_nodes" in dep:
        raise ValueError(
            "deployment.r2lab_experiment_nodes is disabled; auxiliary R2Lab "
            "sensor/edge/RF hosts are not part of the current testbed contract"
        )

    profile_name = dep.get("network_profile")
    if not isinstance(profile_name, str) or not _SAFE_PROFILE_NAME.fullmatch(profile_name):
        raise ValueError("deployment.network_profile must be a safe non-empty profile name")

    ues = dep.get("ues", [])
    if (
        not isinstance(ues, list)
        or not ues
        or not all(
            isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name)
            for name in ues
        )
    ):
        raise ValueError("deployment.ues must be a non-empty list of names")
    if len(ues) != len(set(ues)):
        raise ValueError("deployment.ues must contain unique names")

    host_vars = dep.get("host_vars", {})
    if host_vars is not None and not isinstance(host_vars, dict):
        raise ValueError("deployment.host_vars must be a mapping when provided")
    host_vars = host_vars or {}
    _validate_ssh_policy(dep, host_vars)
    for name in ues:
        values = host_vars.get(name, {}) or {}
        conflicts = sorted(_TRANSPORT_KEYS & set(values))
        if conflicts:
            raise ValueError(
                f"deployment.host_vars.{name} cannot override canonical UE transport fields: "
                + ", ".join(conflicts)
                + "; configure UE transport in deployment/group_vars/all/ue_catalog.yaml"
            )

    for key in ("entrypoint", "config"):
        value = data.get("experiment", {}).get(key)
        if value:
            data["experiment"][key] = str((source.parent / value).resolve())
    for key in ("network_profile_file", "ue_catalog_file", "topology_file"):
        if dep.get(key):
            dep[key] = str((source.parent / dep[key]).resolve())

    network_profile_source = _network_profile_source(dep)
    if not network_profile_source.is_file():
        raise ValueError(f"network profile not found: {network_profile_source}")
    network_profile = yaml.safe_load(network_profile_source.read_text(encoding="utf-8"))
    validate_network_profile(network_profile)

    catalog_source = _ue_catalog_source(dep)
    if not catalog_source.is_file():
        raise ValueError(f"UE catalog not found: {catalog_source}")
    catalog = yaml.safe_load(catalog_source.read_text(encoding="utf-8"))
    validate_ue_catalog(catalog)
    catalog_ues = catalog["ues"]
    for name in ues:
        if name not in catalog_ues:
            raise ValueError(f"selected UE {name!r} is absent from the UE catalog")
        ue_platform = str(catalog_ues[name].get("platform", "")).lower()
        if ue_platform != dep["platform"]:
            raise ValueError(
                f"selected UE {name!r} belongs to platform {ue_platform!r}, "
                f"not {dep['platform']!r}"
            )

    validate_ue_slice_assignments(dep.get("ue_slices"), ues, network_profile)

    data["_source_directory"] = str(source.parent)
    return data


def redacted(data: dict) -> dict:
    clean = copy.deepcopy(data)
    clean.pop("_source_directory", None)
    secret = re.compile(
        r"password|secret|token|credential|private_key|full_key|(?:^|_)opc(?:$|_)",
        re.I,
    )

    def walk(value):
        if isinstance(value, dict):
            return {
                k: ("<redacted>" if secret.search(str(k)) else walk(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(clean)
