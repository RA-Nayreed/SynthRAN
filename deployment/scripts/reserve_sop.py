#!/usr/bin/env python3
import argparse, datetime as dt, json, math, os, subprocess
from pathlib import Path

import yaml

POOL = ["sopnode-f1", "sopnode-f2", "sopnode-f3", "sopnode-w3"]

def run(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check)

def run_visible(*args, check=True):
    process = subprocess.Popen(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output = []
    assert process.stdout is not None
    for line in process.stdout:
        print(f"  {line}", end="", flush=True)
        output.append(line)
    returncode = process.wait()
    result = subprocess.CompletedProcess(args, returncode, "".join(output), "")
    if check and returncode:
        raise subprocess.CalledProcessError(returncode, args, output=result.stdout)
    return result

def stamp(value):
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return parsed

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
    now = dt.datetime.now().astimezone(); end = now + dt.timedelta(minutes=duration)
    events = calendars(); own_active = [e for e in events if e.get("owner") == owner and stamp(e["start_date"]) <= now < stamp(e["end_date"])]
    nodes = dict(deployment["nodes"]); requested = set(nodes.values())
    related = [e for e in own_active if requested.intersection(e["nodes"])]
    active_nodes = set().union(*(set(e["nodes"]) for e in own_active)) if own_active else set()
    own_events = [event for event in events if event.get("owner") == owner]

    def continuous_coverage_end(node):
        coverage_end = now
        relevant = sorted(
            (event for event in own_events if node in event["nodes"]),
            key=lambda event: stamp(event["start_date"]),
        )
        advanced = True
        while advanced:
            advanced = False
            for event in relevant:
                event_start = stamp(event["start_date"])
                event_end = stamp(event["end_date"])
                if event_start <= coverage_end < event_end:
                    coverage_end = event_end
                    advanced = True
        return coverage_end

    if related:
        print("\nActive reservation owned by you:")
        for event in related: print(f"  {', '.join(event['nodes'])}: {event['start_date']} to {event['end_date']}")
        action = choice("How should SynthRAN handle it?", ["Keep it and extend coverage to the requested end time", "Keep its existing time", "Choose a different SOP-node reservation", "Abort deployment"])
        if action == 4: raise SystemExit("Deployment aborted")
        if action == 3: nodes = manual_nodes(nodes); requested = set(nodes.values())
        if action == 2:
            reserved_nodes = list(dict.fromkeys(node for event in related for node in event["nodes"]))
            if not requested.issubset(set(reserved_nodes)):
                nodes = automatic_nodes(nodes, reserved_nodes)
                print("Using the nodes covered by the active reservation:")
                print(f"  core={nodes['core']}, ran={nodes['ran']}, broker={nodes['broker']}")
            deployment["nodes"] = nodes
            path.write_text(yaml.safe_dump(scenario, sort_keys=False))
            Path(args.run_dir, "pos-selection.json").write_text(json.dumps({"nodes": nodes, "duration_minutes": duration, "reused": True}, indent=2) + "\n")
            return
    candidates = available(events, owner, now, end)
    fully_covered_nodes = {
        node for node in requested if continuous_coverage_end(node) >= end
    }
    unavailable = sorted(requested - set(candidates) - fully_covered_nodes)
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

    # POS has create/delete but no in-place calendar update. Preserve every
    # active event and extend coverage with adjacent events only where needed.
    coverage_ends = {node: continuous_coverage_end(node) for node in selected}

    extension_groups = {}
    for node in selected:
        start = max(now, coverage_ends.get(node, now))
        if start < end:
            extension_groups.setdefault(start.replace(second=0, microsecond=0), []).append(node)

    created_ids = []
    try:
        for start, extension_nodes in sorted(extension_groups.items()):
            extension_minutes = max(1, math.ceil((end - start).total_seconds() / 60))
            start_arg = "now" if start <= now else start.strftime("%Y-%m-%d %H:%M:%S")
            result = run(
                "pos", "calendar", "create", "--start", start_arg,
                "--duration", str(extension_minutes), *extension_nodes,
            )
            created_ids.append(result.stdout.strip())
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise SystemExit(
            "Unable to extend SOP calendar coverage; the original active "
            f"reservation was left intact:\n{detail}"
        )

    if created_ids:
        print(f"SOP calendar coverage extended without removing the active event ({', '.join(created_ids)})")
    else:
        print("The active SOP calendar event already covers the requested duration")
    print(f"SOP calendar reservation ready for {', '.join(selected)}")
    newly_allocated = []
    for node in selected:
        print(f"Allocating {node} for this deployment", flush=True)
        if node in active_nodes:
            print(f"Reusing the active allocation for {node}", flush=True)
            continue
        allocation = run_visible("pos", "allocations", "allocate", node, check=False)
        allocation_text = allocation.stdout
        allocation_lower = allocation_text.lower()
        already_active = (
            "already allocated" in allocation_lower
            or "a command for allocation" in allocation_lower
        )
        if allocation.returncode and not already_active:
            raise SystemExit(allocation_text.strip())
        if allocation.returncode == 0:
            newly_allocated.append(node)
        elif already_active:
            print(f"Reusing the active allocation for {node}", flush=True)
    for node in newly_allocated:
        print(f"Selecting image {image} on {node}", flush=True)
        run_visible("pos", "nodes", "image", node, image)
        print(f"Resetting {node}; waiting for POS to report boot completion", flush=True)
        run_visible("pos", "nodes", "reset", "--blocking", "--verbose", node)
        print(f"{node} finished its POS reset", flush=True)
    deployment["nodes"] = nodes
    path.write_text(yaml.safe_dump(scenario, sort_keys=False))
    Path(args.run_dir, "pos-selection.json").write_text(json.dumps({"nodes": nodes, "duration_minutes": duration}, indent=2) + "\n")

if __name__ == "__main__": main()
