"""Prompt for deployment choices using the selected configuration as defaults."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .scenario import load_scenario
from .experiment import invoke


def choose(label: str, default: str, choices=()) -> str:
    options = f" ({', '.join(choices)})" if choices else ""
    value = input(f"{label}{options} [{default}]: ").strip() or default
    if choices and value not in choices:
        raise ValueError(f'{label}: choose one of {", ".join(choices)}')
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    scenario = load_scenario(args.source)
    dep = scenario["deployment"]
    dep["core"] = choose("Core", dep["core"], ("open5gs", "oai", "free5gc"))
    dep["ran"] = choose("RAN", dep["ran"].lower(), ("srsran", "oai", "ueransim"))
    dep["platform"] = choose(
        "Platform", dep["platform"], ("rfsim", "r2lab", "physical")
    )
    dep["ru"] = (
        "rfsim"
        if dep["platform"] == "rfsim"
        else choose("Radio unit", dep.get("ru", ""))
    )
    for role in dep["nodes"]:
        dep["nodes"][role] = choose(f"{role.title()} host", dep["nodes"][role])
    dep["profile"] = choose("5G profile", dep.get("profile", "default"))
    profile_path = (
        Path("deployment/group_vars/all") / f"5g_profile_{dep['profile']}.yaml"
    )
    if profile_path.is_file():
        profile = yaml.safe_load(profile_path.read_text())
        print("Profile UEs: " + ", ".join(profile.get("ues", {})))
    selected = choose("UE names (comma separated)", ",".join(dep["ues"]))
    dep["ues"] = [name.strip() for name in selected.split(",")]
    if dep["platform"] == "r2lab":
        dep["r2lab_username"] = choose(
            "R2Lab slice username (blank uses SSH config)",
            dep.get("r2lab_username", ""),
        )
    for key, label in [("reservation", "SOP"), ("r2lab_reservation", "R2Lab")]:
        if key == "r2lab_reservation" and dep["platform"] != "r2lab":
            continue
        settings = dep.setdefault(key, {})
        settings["enabled"] = (
            choose(
                f"{label} reservation",
                str(settings.get("enabled", True)).lower(),
                ("true", "false"),
            )
            == "true"
        )
        if settings["enabled"]:
            settings["duration_minutes"] = int(
                choose(
                    f"{label} duration in minutes",
                    str(settings.get("duration_minutes", 120)),
                )
            )
    scenario.pop("_source_directory", None)
    print(yaml.safe_dump({"deployment": dep}, sort_keys=False))
    if choose("Continue", "yes", ("yes", "no")) != "yes":
        raise SystemExit("Cancelled")
    Path(args.output).write_text(yaml.safe_dump(scenario, sort_keys=False))
    invoke("configure", args.output, source_config=args.source)


if __name__ == "__main__":
    main()
