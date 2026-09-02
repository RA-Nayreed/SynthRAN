#!/usr/bin/env python3
import argparse, datetime as dt, itertools, json, os, subprocess, sys
from pathlib import Path

import yaml

POOL = ["sopnode-f1", "sopnode-f2", "sopnode-f3", "sopnode-w3"]

def run(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check)

def stamp(value):
    return dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

def calendars(owner=None):
    command = ["pos", "calendar", "list", "--json"]
    if owner:
        command[3:3] = ["--filter", f"owner={owner}"]
    return json.loads(run(*command).stdout)

def choice(title, options):
    print(f"\n{title}")
    for index, option in enumerate(options, 1): print(f"{index}) {option}")
    while True:
        answer = input(f"Enter choice [1-{len(options)}]: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(options): return int(answer)

def manual_nodes(nodes):
    result = dict(nodes)
    for role in ("core", "ran", "broker"):
        print(f"\nChoose replacement {role} node (current: {result[role]})")
        for index, node in enumerate(POOL, 1): print(f"{index}) {node}")
        answer = input("Enter choice [1-4]: ").strip()
        if answer: result[role] = POOL[int(answer) - 1]
    return result

def available(events, owner, start, end):
    busy = set()
    for event in events:
        if event.get("owner") == owner: continue
        if stamp(event["start_date"]) < end and stamp(event["end_date"]) > start:
            busy.update(event["nodes"])
    return [node for node in POOL if node not in busy]

def automatic_nodes(nodes, candidates):
    distinct = nodes["core"] != nodes["ran"]
    pairs = [(a, b) for a in candidates for b in candidates if not distinct or a != b]
    if not pairs: raise SystemExit("No usable SOP core/RAN pair is available now")
    pairs.sort(key=lambda pair: (-(pair[0] == nodes["core"]), -(pair[1] == nodes["ran"]), POOL.index(pair[0]), POOL.index(pair[1])))
    core, ran = pairs[0]
    broker = nodes["broker"] if nodes["broker"] in candidates else core
    return {"core": core, "ran": ran, "broker": broker}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config"); parser.add_argument("run_dir")
    args = parser.parse_args(); path = Path(args.config)
    scenario = yaml.safe_load(path.read_text()); deployment = scenario["deployment"]
    reservation = deployment.get("reservation", {})
    if not reservation.get("enabled", True): return
    duration = int(reservation.get("duration_minutes", 120)); image = reservation.get("image", "ubuntu-jammy")
    owner = os.environ.get("USER") or run("id", "-un").stdout.strip()
    now = dt.datetime.now(); end = now + dt.timedelta(minutes=duration)
    events = calendars(); own_active = [e for e in events if e.get("owner") == owner and stamp(e["start_date"]) <= now < stamp(e["end_date"])]
    nodes = dict(deployment["nodes"]); requested = set(nodes.values())
    related = [e for e in own_active if requested.intersection(e["nodes"])]
    old_nodes = set().union(*(set(e["nodes"]) for e in related)) if related else set()
    if related:
        print("\nActive reservation owned by you:")
        for event in related: print(f"  {', '.join(event['nodes'])}: {event['start_date']} to {event['end_date']}")
        action = choice("How should SynthRAN handle it?", ["Change it to start now for the requested duration", "Keep its existing time", "Choose a different SOP-node reservation", "Abort deployment"])
        if action == 4: raise SystemExit("Deployment aborted")
        if action == 3: nodes = manual_nodes(nodes); requested = set(nodes.values())
        if action == 2:
            deployment["nodes"] = nodes; path.write_text(yaml.safe_dump(scenario, sort_keys=False)); return
        for event in related:
            run("pos", "calendar", "delete", "--id", str(event["id"]), *event["nodes"])
    candidates = available(events, owner, now, end)
    unavailable = sorted(requested - set(candidates) - old_nodes)
    if unavailable:
        print("\nUnavailable SOP nodes: " + ", ".join(unavailable))
        action = choice("How should SynthRAN continue?", ["Automatically use available SOP nodes", "Choose replacement nodes manually", "Keep selected nodes and reserve the earliest available time", "Abort deployment"])
        if action == 4: raise SystemExit("Deployment aborted")
        if action == 1: nodes = automatic_nodes(nodes, candidates)
        elif action == 2: nodes = manual_nodes(nodes)
        else:
            result = run("pos", "calendar", "create", "--asap", "--duration", str(duration), *sorted(requested))
            print(result.stdout.strip()); raise SystemExit("Future reservation created; rerun deploy.sh when it becomes active")
    selected = list(dict.fromkeys(nodes.values()))
    result = run("pos", "calendar", "create", "--start", "now", "--duration", str(duration), *selected)
    print(result.stdout.strip())
    new_nodes = [node for node in selected if node not in old_nodes]
    for node in selected:
        allocation = run("pos", "allocations", "allocate", node, check=False)
        if allocation.returncode and "already allocated" not in allocation.stderr + allocation.stdout:
            raise SystemExit((allocation.stderr or allocation.stdout).strip())
    for node in new_nodes:
        run("pos", "nodes", "image", node, image)
        run("pos", "nodes", "reset", "--blocking", "--verbose", node)
    deployment["nodes"] = nodes
    path.write_text(yaml.safe_dump(scenario, sort_keys=False))
    Path(args.run_dir, "pos-selection.json").write_text(json.dumps({"nodes": nodes, "duration_minutes": duration}, indent=2) + "\n")

if __name__ == "__main__": main()
