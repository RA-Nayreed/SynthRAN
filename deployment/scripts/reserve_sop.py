#!/usr/bin/env python3
import argparse, datetime as dt, json, math, os, subprocess
from pathlib import Path

import yaml

POOL = ["sopnode-f1", "sopnode-f2", "sopnode-f3", "sopnode-w3"]
STATE_PATH = Path(".synthran/pos-reservation.json")

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

def available(events, start, end, ignored_ids=()):
    ignored_ids = {str(event_id) for event_id in ignored_ids}
    busy = set()
    for event in events:
        if str(event.get("id")) in ignored_ids:
            continue
        if stamp(event["start_date"]) < end and stamp(event["end_date"]) > start:
            busy.update(event["nodes"])
    return [node for node in POOL if node not in busy]

def load_managed_state():
    try:
        state = json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return state if state.get("managed_by") == "synthran" else {}

def save_managed_state(event_id, nodes, start, end):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({
        "event_id": str(event_id),
        "nodes": nodes,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "managed_by": "synthran",
    }, indent=2) + "\n")

def restore_event(event):
    restore_now = dt.datetime.now().astimezone()
    event_start = stamp(event["start_date"])
    event_end = stamp(event["end_date"])
    if event_end <= restore_now:
        return
    start = max(event_start, restore_now)
    duration = max(1, math.ceil((event_end - start).total_seconds() / 60))
    start_arg = "now" if event_start <= restore_now else event_start.strftime("%Y-%m-%d_%H:%M")
    run(
        "pos", "calendar", "create", "--start", start_arg,
        "--duration", str(duration), *event["nodes"], check=False,
    )

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
    managed_state = load_managed_state()
    managed_event_id = str(managed_state.get("event_id", ""))
    managed_events = [
        event for event in events
        if managed_event_id
        and str(event.get("id")) == managed_event_id
        and event.get("owner") == owner
        and requested.intersection(event["nodes"])
    ]
    replace_events = []
    reuse_reservation = False

    if related:
        print("\nActive reservation owned by you:")
        for event in related: print(f"  {', '.join(event['nodes'])}: {event['start_date']} to {event['end_date']}")
        action = choice("How should SynthRAN handle it?", ["Replace it with a reservation starting now for the requested duration", "Keep its existing time", "Choose a different SOP-node reservation", "Abort deployment"])
        if action == 4: raise SystemExit("Deployment aborted")
        if action == 3: nodes = manual_nodes(nodes); requested = set(nodes.values())
        if action == 2:
            reserved_nodes = list(dict.fromkeys(node for event in related for node in event["nodes"]))
            if not requested.issubset(set(reserved_nodes)):
                nodes = automatic_nodes(nodes, reserved_nodes)
                print("Using the nodes covered by the active reservation:")
                print(f"  core={nodes['core']}, ran={nodes['ran']}, broker={nodes['broker']}")
            requested = set(nodes.values())
            reuse_reservation = True
        if action == 1:
            replace_events = list({str(event["id"]): event for event in related + managed_events}.values())

    if reuse_reservation:
        selected = list(dict.fromkeys(nodes.values()))
        print(f"Keeping the active SOP calendar reservation for {', '.join(selected)}")
    else:
        replace_ids = [event["id"] for event in replace_events]
        candidates = available(events, now, end, replace_ids)
        unavailable = sorted(requested - set(candidates))
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
        deleted = []
        try:
            for event in replace_events:
                run("pos", "calendar", "delete", "--id", str(event["id"]), *event["nodes"])
                deleted.append(event)
            result = run(
                "pos", "calendar", "create", "--start", "now",
                "--duration", str(duration), *selected,
            )
        except subprocess.CalledProcessError as error:
            for event in deleted:
                restore_event(event)
            detail = (error.stderr or error.stdout or str(error)).strip()
            raise SystemExit(
                "Unable to replace the SOP calendar reservation; previous remaining "
                f"coverage was restored where possible:\n{detail}"
            )
        reservation_id = result.stdout.strip()
        save_managed_state(reservation_id, selected, now, end)
        print(f"SOP calendar reservation ready (event {reservation_id}) for {', '.join(selected)}")

    # Calendar ownership does not imply that POS has allocated and booted a
    # node. Always ask POS to allocate each selected node. POS reports an
    # already-active allocation without reprovisioning it, while a successful
    # new allocation is imaged and reset below.
    newly_allocated = []
    for node in selected:
        print(f"Verifying the POS allocation for {node}", flush=True)
        allocation = run_visible("pos", "allocations", "allocate", node, check=False)
        allocation_text = allocation.stdout
        allocation_lower = allocation_text.lower()
        already_active = "already allocated" in allocation_lower
        allocation_in_progress = "a command for allocation" in allocation_lower
        if allocation_in_progress:
            raise SystemExit(
                f"POS is still processing an allocation command for {node}. "
                "Wait for that command to finish, then rerun SynthRAN."
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
    Path(args.run_dir, "pos-selection.json").write_text(json.dumps({
        "nodes": nodes,
        "duration_minutes": duration,
        "reused": reuse_reservation,
        "reused_reservation": reuse_reservation,
        "newly_allocated_nodes": newly_allocated,
    }, indent=2) + "\n")

if __name__ == "__main__": main()
