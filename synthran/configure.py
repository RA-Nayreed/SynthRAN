"""Interactive deployment configuration for the public deploy.sh frontend."""

from __future__ import annotations

import argparse
import copy
import os
import re
from pathlib import Path

import yaml

from .experiment import invoke
from .scenario import load_scenario

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "deployment/group_vars/all"
DEFAULT_SOP_NODES = ["sopnode-f1", "sopnode-f2", "sopnode-f3", "sopnode-w3"]
R2LAB_RADIOS = [
    ("n300", "USRP N300, SophiaNode fiber, 2x2 antenna"),
    ("n320", "USRP N320, SophiaNode fiber, 4x4 antenna"),
    ("benetel1", "RAN550 O-RU, band n78, 4T4R, 100 MHz"),
    ("benetel2", "RAN550 O-RU, band n78, 4T4R, 100 MHz"),
]
BANNER = r"""
  _____             _   _     _____            _   _
 / ____|           | | | |   |  __ \     /\   | \ | |
| (___  _   _ _ __ | |_| |__ | |__) |   /  \  |  \| |
 \___ \| | | | '_ \| __| '_ \|  _  /   / /\ \ | . ` |
 ____) | |_| | | | | |_| | | | | \ \  / ____ \| |\  |
|_____/ \__, |_| |_|\__|_| |_|_|  \_\/_/    \_\_| \_|
         __/ |
        |___/       Energy-aware 5G/6G deployment
"""


def default_scenario() -> dict:
    """Return infrastructure defaults without depending on a reference scenario."""
    return {
        "deployment": {
            "core": "open5gs",
            "ran": "srsran",
            "platform": "rfsim",
            "ru": "rfsim",
            "profile": "default",
            "nodes": {
                "core": "sopnode-f2",
                "ran": "sopnode-f3",
                "broker": "sopnode-f2",
            },
            "host_vars": {"sopnode-f3": {"cpu_low_latency": True}},
            "ues": ["uesim01", "uesim02"],
            "reservation": {
                "enabled": True,
                "duration_minutes": 120,
                "image": "ubuntu-jammy",
            },
            "r2lab_reservation": {"enabled": True, "duration_minutes": 120},
        }
    }


def numbered(label: str, options: list[tuple[str, str]], default: str) -> str:
    values = [value for value, _description in options]
    if default not in values:
        options = [(default, "loaded configuration"), *options]
        values = [value for value, _description in options]
    default_index = values.index(default) + 1
    print()
    print(f"{label} (default: {default})")
    for index, (value, description) in enumerate(options, 1):
        suffix = f" — {description}" if description else ""
        print(f"  {index}) {value}{suffix}")
    raw = input(f"Enter choice [1-{len(options)}]: ").strip()
    if not raw:
        return default
    if not raw.isdigit() or not 1 <= int(raw) <= len(options):
        raise ValueError(f"Invalid choice for {label}")
    return options[int(raw) - 1][0]


def yes_no(label: str, default: bool) -> bool:
    prompt = "Y/n" if default else "y/N"
    value = input(f"{label}? [{prompt}]: ").strip().lower()
    if not value:
        return default
    if value in {"y", "yes"}:
        return True
    if value in {"n", "no"}:
        return False
    raise ValueError(f"{label}: answer yes or no")


def positive_int(label: str, default: int) -> int:
    value = input(f"{label} [{default}]: ").strip()
    if not value:
        return int(default)
    if not value.isdigit() or int(value) <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return int(value)


def text(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def available_profiles() -> list[str]:
    names = []
    for path in sorted(PROFILE_DIR.glob("5g_profile_*.yaml")):
        names.append(path.stem.removeprefix("5g_profile_"))
    if not names:
        raise ValueError("No 5G profiles are available")
    return names


def profile_path(deployment: dict) -> Path:
    custom = deployment.get("profile_file")
    if custom:
        return Path(custom)
    return PROFILE_DIR / f"5g_profile_{deployment.get('profile', 'default')}.yaml"


def profile_ues(deployment: dict) -> list[str]:
    path = profile_path(deployment)
    if not path.is_file():
        raise ValueError(f"5G profile not found: {path}")
    profile = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list((profile.get("ues") or {}).keys())


def parse_index_selection(value: str, names: list[str]) -> list[str]:
    chosen: list[str] = []
    for part in value.replace(" ", "").split(","):
        if not part:
            continue
        if part in names:
            selected = [part]
        else:
            bounds = part.split("-", 1)
            try:
                start = int(bounds[0])
                stop = int(bounds[-1])
            except ValueError as error:
                raise ValueError(f"Invalid UE selection: {part}") from error
            if start > stop or start < 1 or stop > len(names):
                raise ValueError(
                    f"UE range must be ascending and within 1-{len(names)}: {part}"
                )
            selected = names[start - 1 : stop]
        for name in selected:
            if name not in chosen:
                chosen.append(name)
    return chosen


def choose_ues(deployment: dict, original_platform: str) -> list[str]:
    platform = deployment["platform"]
    available = profile_ues(deployment)
    current = list(deployment.get("ues", []))
    if platform == "rfsim":
        software = [name for name in available if name.startswith("uesim")]
        default = current if original_platform == "rfsim" else software[:2]
        rendered = ",".join(default or software[:2])
        selected = text("UEs, comma-separated", rendered)
        names = [name.strip() for name in selected.split(",") if name.strip()]
    elif platform == "r2lab":
        physical = [name for name in available if re.fullmatch(r"q(?:hat|fit)[A-Za-z0-9_.-]+", name)]
        if not physical:
            raise ValueError("Selected 5G profile contains no supported R2Lab physical UEs")
        print("\nPhysical 5G UEs")
        for index, name in enumerate(physical, 1):
            print(f"  {index:2d}) {name}")
        default = current if original_platform == "r2lab" and set(current) <= set(physical) else [physical[0]]
        rendered = ",".join(default)
        selected = text(
            "Physical UEs by name or number/range (for example qhat01,qfit07 or 1-3,10)",
            rendered,
        )
        names = parse_index_selection(selected, physical)
    else:
        rendered = ",".join(current)
        selected = text("Physical UE host names, comma-separated", rendered)
        names = [name.strip() for name in selected.split(",") if name.strip()]
    if not names:
        raise ValueError("At least one UE is required")
    if len(names) != len(set(names)):
        raise ValueError("UE names must be unique")
    return names


def sop_nodes(deployment: dict) -> list[str]:
    configured = list((deployment.get("reservation") or {}).get("node_pool", []))
    configured += list((deployment.get("nodes") or {}).values())
    return list(dict.fromkeys([*DEFAULT_SOP_NODES, *configured]))


def show_r2lab_matrix() -> None:
    print("\nR2Lab resource matrix")
    print("---------------------")
    print("5G radio units selectable by SynthRAN")
    for index, (name, description) in enumerate(R2LAB_RADIOS, 1):
        print(f"  {index}) {name:<9} {description}")
    print("\nPhysical UE choices are read from the selected 5G profile, not duplicated here.")
    print("Availability and health are verified during reservation and provisioning.")


def configure(args: argparse.Namespace) -> None:
    if args.source:
        scenario = load_scenario(args.source)
    else:
        scenario = default_scenario()
    if args.testbed_only:
        scenario.pop("experiment", None)

    dep = scenario["deployment"]
    original_platform = dep.get("platform", "rfsim")
    experiment_source = (scenario.get("experiment") or {}).get("config")

    print("\033[1;36m" + BANNER + "\033[0m")
    dep["core"] = numbered(
        "Which CORE do you want to deploy?",
        [("oai", "OAI"), ("open5gs", "Open5GS"), ("free5gc", "Free5GC")],
        dep.get("core", "open5gs"),
    )
    dep["ran"] = numbered(
        "Which RAN do you want to deploy?",
        [("oai", "OAI"), ("srsran", "srsRAN"), ("ueransim", "UERANSIM")],
        str(dep.get("ran", "srsran")).lower(),
    )
    dep["platform"] = numbered(
        "Which platform do you want to use?",
        [
            ("rfsim", "software RF simulation"),
            ("r2lab", "R2Lab physical radio"),
            ("physical", "externally managed physical hosts"),
        ],
        dep.get("platform", "rfsim"),
    )
    if dep["platform"] == "r2lab" and dep["ran"] == "ueransim":
        raise ValueError("UERANSIM is a software RAN and cannot drive an R2Lab physical radio")

    if dep["platform"] == "rfsim":
        dep["ru"] = "rfsim"
    elif dep["platform"] == "r2lab":
        show_r2lab_matrix()
        radio_options = list(R2LAB_RADIOS)
        current_ru = dep.get("ru", "n300")
        dep["ru"] = numbered("Which radio unit do you want to use?", radio_options, current_ru)
        username = os.environ.get("R2LAB_USERNAME") or dep.get("r2lab_username", "")
        dep["r2lab_username"] = text(
            "R2Lab username / slice name (blank uses SSH configuration)", username
        )
    else:
        dep["ru"] = text("Physical radio unit identifier", dep.get("ru", "physical"))

    node_choices = [(name, "") for name in sop_nodes(dep)]
    nodes = dep.setdefault("nodes", {})
    nodes["core"] = numbered(
        "Which SOP node should host the core?", node_choices, nodes.get("core", "sopnode-f2")
    )
    nodes["ran"] = numbered(
        "Which SOP node should host the RAN?", node_choices, nodes.get("ran", "sopnode-f3")
    )
    # Preserve the old interactive behavior: broker/N6 endpoint follows the core.
    nodes["broker"] = nodes["core"]

    if not dep.get("profile_file"):
        profiles = available_profiles()
        dep["profile"] = numbered(
            "Which 5G profile do you want to use?",
            [(name, "") for name in profiles],
            dep.get("profile", "default"),
        )
    else:
        print(f"\nUsing explicit 5G profile file: {dep['profile_file']}")

    dep["ues"] = choose_ues(dep, original_platform)

    reservation = dep.setdefault("reservation", {})
    reservation["enabled"] = yes_no(
        "Ensure the selected SOP nodes are reserved", reservation.get("enabled", True)
    )
    if reservation["enabled"]:
        reservation["duration_minutes"] = positive_int(
            "Reservation duration in minutes", reservation.get("duration_minutes", 120)
        )
        reservation["image"] = text("POS image", reservation.get("image", "ubuntu-jammy"))

    if dep["platform"] == "r2lab":
        r2 = dep.setdefault("r2lab_reservation", {})
        r2["enabled"] = yes_no("Reserve the R2Lab testbed", r2.get("enabled", True))
        if r2["enabled"]:
            r2["duration_minutes"] = positive_int(
                "R2Lab reservation duration in minutes", r2.get("duration_minutes", 120)
            )
    else:
        dep.setdefault("r2lab_reservation", {})["enabled"] = False

    scenario.pop("_source_directory", None)
    print("\nDeployment summary")
    print(f"  Core:       {dep['core']} on {nodes['core']}")
    print(f"  RAN:        {dep['ran']} on {nodes['ran']}")
    print(f"  Broker:     {nodes['broker']}")
    print(f"  Platform:   {dep['platform']} ({dep.get('ru', '')})")
    print(f"  Profile:    {dep.get('profile_file') or dep.get('profile', 'default')}")
    print(f"  UEs:        {', '.join(dep['ues'])}")
    print(
        "  SOP reserve: "
        + (f"yes, {reservation.get('duration_minutes', 120)}m" if reservation["enabled"] else "no")
    )
    if dep["platform"] == "r2lab":
        r2 = dep["r2lab_reservation"]
        print(
            "  R2Lab:      "
            + (f"yes, {r2.get('duration_minutes', 120)}m" if r2.get("enabled") else "no")
        )
    if scenario.get("experiment"):
        print(f"  Experiment: {scenario['experiment'].get('config', 'configured')}")
    else:
        print("  Experiment: testbed only")

    if not yes_no("Continue", True):
        raise SystemExit("Cancelled")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8")

    # If an explicit scenario already selected a generic experiment, let that
    # experiment adapt its scientific configuration to the newly chosen UEs.
    # Pass the experiment's own config, not the outer testbed scenario.
    if scenario.get("experiment") and experiment_source and not args.testbed_only:
        invoke("configure", output, source_config=experiment_source)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source")
    parser.add_argument("--output", required=True)
    parser.add_argument("--testbed-only", action="store_true")
    configure(parser.parse_args())


if __name__ == "__main__":
    main()
