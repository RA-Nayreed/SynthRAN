#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "experiments/exp2/pilot-plan-v1.json"
PILOT_DEFAULT = ROOT / "results/exp2-matched-trace/pilot-seed1001"
SCENARIO_NAME = "rfsim-oai-srsran-3ue.yml"
COMPETING_UE = "uesim03"


def die(msg):
    raise SystemExit(msg)


def run(cmd, capture=False, check=True):
    print("\n$ " + " ".join(shlex.quote(str(x)) for x in cmd), flush=True)
    p = subprocess.run(
        [str(x) for x in cmd],
        cwd=ROOT,
        text=True,
        capture_output=capture,
        check=False,
    )
    if capture and p.stdout:
        print(p.stdout, end="" if p.stdout.endswith("\n") else "\n")
    if p.returncode and check:
        if capture and p.stderr:
            print(p.stderr, file=sys.stderr)
        die(f"command failed with exit {p.returncode}")
    return p


def json_line(text):
    for line in reversed(text.splitlines()):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    die("expected JSON output was not found")


def result_dirs():
    r = ROOT / "results"
    if not r.exists():
        return set()
    return {p.resolve() for p in r.iterdir() if p.is_dir() and p.name.startswith("20")}


def deploy(args):
    before = result_dirs()
    p = run([ROOT / "deploy.sh", *args], check=False)
    after = result_dirs()
    created = sorted(after - before, key=lambda p: p.stat().st_mtime_ns)
    if not created:
        die("deploy.sh created no run directory")
    rd = created[-1]
    print(f"run={rd.relative_to(ROOT)}")
    if p.returncode:
        die(f"deploy.sh failed; artifacts retained in {rd}")
    return rd


def ensure_inputs(pilot, exp1):
    required = [
        pilot / "pilot-source-selection.json",
        pilot / "native/model/events.jsonl",
        pilot / "gap_permutation/model/events.jsonl",
        pilot / "periodic/model/events.jsonl",
    ]
    if not all(p.exists() for p in required):
        if pilot.exists():
            die(f"incomplete pilot directory exists: {pilot}")
        run([
            sys.executable,
            ROOT / "experiments/exp2/prepare_pilot.py",
            "--experiment1-root", exp1,
            "--output", pilot,
        ])

    scenario = pilot / SCENARIO_NAME
    if not scenario.exists():
        run([
            sys.executable,
            ROOT / "experiments/exp2/prepare_transport_scenario.py",
            "--pilot-root", pilot,
            "--output", scenario,
        ])
    data = yaml.safe_load(scenario.read_text())
    d = data["deployment"]
    if (d["core"], d["ran"], d["platform"]) != ("oai", "srsran", "rfsim"):
        die("transport scenario is not frozen OAI+srsRAN RFSIM")
    if d.get("ues", [])[-1:] != [COMPETING_UE]:
        die("transport scenario does not reserve uesim03 as the competing UE")
    return scenario


def binding(run_dir, device):
    d = json.loads((run_dir / "live-deployment-evidence.json").read_text())
    items = [x for x in d["bindings"] if x["device"] == device]
    if len(items) != 1:
        die(f"expected one binding for {device}, got {len(items)}")
    return items[0]


def broker_ip(host):
    p = run([
        "ssh", host,
        "ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i==\"src\") {print $(i+1); exit}}'"
    ], capture=True)
    value = p.stdout.strip().splitlines()[-1].strip()
    if not value:
        die(f"could not resolve broker address on {host}")
    return value


def stage_tools(ran, broker, b):
    run(["scp", ROOT / "experiments/exp2/udp_receiver.py", f"{broker}:/tmp/exp2_udp_receiver.py"])
    run(["scp", ROOT / "experiments/exp2/udp_sender.py", f"{ran}:/tmp/exp2_udp_sender.py"])
    remote = (
        f"kubectl cp -n {shlex.quote(b['namespace'])} -c {shlex.quote(b['container'])} "
        f"/tmp/exp2_udp_sender.py {shlex.quote(b['pod'])}:/tmp/exp2_udp_sender.py"
    )
    run(["ssh", ran, remote])


def prove_route(ran, b, dst):
    remote = (
        f"kubectl exec -n {shlex.quote(b['namespace'])} {shlex.quote(b['pod'])} "
        f"-c {shlex.quote(b['container'])} -- "
        f"ip route get {shlex.quote(dst)} from {shlex.quote(b['address'])}"
    )
    p = run(["ssh", ran, remote], capture=True)
    if b["interface"] not in p.stdout or f"from {b['address']}" not in p.stdout:
        die("competing traffic route is not using its assigned 5G tunnel")
    return p.stdout.strip()


def udp_probe(ran, broker, b, dst, rate, seconds, packet_bytes, port):
    rx = subprocess.Popen(
        [
            "ssh", "-n", broker,
            f"python3 /tmp/exp2_udp_receiver.py --port {port} "
            "--startup-timeout-seconds 30 --idle-timeout-seconds 2"
        ],
        cwd=ROOT, text=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    time.sleep(0.75)
    remote = (
        f"kubectl exec -n {shlex.quote(b['namespace'])} {shlex.quote(b['pod'])} "
        f"-c {shlex.quote(b['container'])} -- "
        f"python3 /tmp/exp2_udp_sender.py --destination {shlex.quote(dst)} "
        f"--port {port} --bind-address {shlex.quote(b['address'])} "
        f"--rate-mbps {rate:g} --duration-seconds {seconds:g} --packet-bytes {packet_bytes}"
    )
    txp = run(["ssh", ran, remote], capture=True, check=False)
    if txp.returncode:
        rx.terminate()
        rx.communicate(timeout=5)
        die(f"sender failed at {rate:g} Mbps")
    out, err = rx.communicate(timeout=seconds + 15)
    if rx.returncode:
        die(f"receiver failed at {rate:g} Mbps: {err}")
    tx = json_line(txp.stdout)
    rj = json_line(out)
    sent = int(tx["packets_attempted"])
    received = int(rj["packets_received"])
    return {
        "rate_mbps": rate,
        "sender": tx,
        "receiver": rj,
        "end_to_end": {
            "packets_attempted": sent,
            "packets_received": received,
            "packets_lost": max(sent - received, 0),
            "delivery_ratio": received / sent if sent else 0.0,
        },
    }


def calibrate(plan, scenario, baseline, outdir):
    cfg = yaml.safe_load(scenario.read_text())
    nodes = cfg["deployment"]["nodes"]
    ran, broker = nodes["ran"], nodes["broker"]
    b = binding(baseline, COMPETING_UE)
    dst = broker_ip(broker)
    stage_tools(ran, broker, b)
    route = prove_route(ran, b, dst)

    cal = plan["transport_calibration"]
    rates = [float(x) for x in cal["offered_payload_mbps_grid"]]
    threshold = float(cal["delivery_threshold"])
    seconds = float(cal["probe_duration_seconds"])
    packet_bytes = int(cal["packet_bytes"])
    probes = []
    crossing = None

    cdir = outdir / "calibration"
    cdir.mkdir(parents=True)
    for i, rate in enumerate(rates):
        print(f"\n=== {rate:g} Mbps ===")
        p = udp_probe(ran, broker, b, dst, rate, seconds, packet_bytes, 39001 + i)
        probes.append(p)
        (cdir / f"{i+1:02d}-{rate:g}mbps.json").write_text(json.dumps(p, indent=2) + "\n")
        ratio = p["end_to_end"]["delivery_ratio"]
        print(f"delivery_ratio={ratio:.6f}")
        if crossing is None and ratio < threshold:
            crossing = i

    if crossing is None:
        status, lstar = "no-threshold-crossing", None
    elif crossing == 0:
        status, lstar = "first-grid-rate-already-saturated", None
    else:
        status, lstar = "knee-selected", rates[crossing - 1]

    summary = {
        "status": status,
        "route": route,
        "competing_ue": b,
        "broker_address": dst,
        "delivery_threshold": threshold,
        "l_star_mbps": lstar,
        "probes": probes,
    }
    (cdir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if lstar is None:
        die(f"calibration stopped with {status}; no L* selected")
    print(f"\nL*={lstar:g} Mbps")
    return lstar, ran, broker, b, dst


def start_bg(ran, broker, b, dst, rate, seconds, packet_bytes, port):
    rx = subprocess.Popen(
        [
            "ssh", "-n", broker,
            f"python3 /tmp/exp2_udp_receiver.py --port {port} "
            "--startup-timeout-seconds 30 --idle-timeout-seconds 3"
        ],
        cwd=ROOT, text=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    time.sleep(0.75)
    remote = (
        f"kubectl exec -n {shlex.quote(b['namespace'])} {shlex.quote(b['pod'])} "
        f"-c {shlex.quote(b['container'])} -- "
        f"python3 /tmp/exp2_udp_sender.py --destination {shlex.quote(dst)} "
        f"--port {port} --bind-address {shlex.quote(b['address'])} "
        f"--rate-mbps {rate:g} --duration-seconds {seconds:g} --packet-bytes {packet_bytes}"
    )
    tx = subprocess.Popen(
        ["ssh", ran, remote],
        cwd=ROOT, text=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return tx, rx


def finish_bg(tx, rx, timeout):
    txo, txe = tx.communicate(timeout=timeout)
    rxo, rxe = rx.communicate(timeout=10)
    if tx.returncode:
        die(f"background sender failed: {txe}")
    if rx.returncode:
        die(f"background receiver failed: {rxe}")
    tj, rj = json_line(txo), json_line(rxo)
    sent = int(tj["packets_attempted"])
    rec = int(rj["packets_received"])
    return {
        "sender": tj,
        "receiver": rj,
        "delivery_ratio": rec / sent if sent else 0.0,
        "packets_lost": max(sent - rec, 0),
    }


def matched_block(plan, scenario, pilot, baseline, outdir, lstar, ran, broker, b, dst):
    cfg = yaml.safe_load(scenario.read_text())
    mqtt = cfg.get("mqtt", {})
    model = cfg.get("model", {})
    horizon = float(model.get("duration_seconds", float(model.get("duration_ms", 60000)) / 1000))
    bg_seconds = horizon + float(mqtt.get("start_delay_seconds", 30)) + float(mqtt.get("drain_seconds", 60)) + 90
    packet_bytes = int(plan["transport_calibration"]["packet_bytes"])

    variants = list(plan["timing_interventions"]["variants"])
    random.Random(int(plan["matched_pilot"]["variant_order_seed"])).shuffle(variants)

    mdir = outdir / "matched-pilot"
    mdir.mkdir(parents=True)
    manifest = {"l_star_mbps": lstar, "variant_order": variants, "runs": []}
    (mdir / "plan.json").write_text(json.dumps(manifest, indent=2) + "\n")

    for i, variant in enumerate(variants):
        print(f"\n=== {variant} @ L*={lstar:g} Mbps ===")
        tx, rx = start_bg(ran, broker, b, dst, lstar, bg_seconds, packet_bytes, 39101 + i)
        time.sleep(2)
        try:
            rd = deploy([
                "--config", scenario,
                "--workload-only",
                "--prepared-workload", pilot / variant / "model",
            ])
        except BaseException:
            tx.terminate()
            rx.terminate()
            raise
        bg = finish_bg(tx, rx, bg_seconds + 30)
        (rd / "exp2-background-load.json").write_text(json.dumps(bg, indent=2) + "\n")
        summary = json.loads((rd / "summary.json").read_text())
        manifest["runs"].append({
            "variant": variant,
            "run_dir": str(rd.relative_to(ROOT)),
            "background": bg,
            "measurement": summary.get("measurement"),
            "five_g": summary.get("five_g"),
            "experimental_coverage": summary.get("experimental_coverage"),
        })
        (mdir / "summary.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--experiment1-root",
        type=Path,
        default=Path.home() / "SynthRAN/results/exp1-energy-correlation",
    )
    ap.add_argument("--pilot-root", type=Path, default=PILOT_DEFAULT)
    ap.add_argument("--prepare-only", action="store_true")
    args = ap.parse_args()

    plan = json.loads(PLAN.read_text())
    pilot = args.pilot_root.expanduser().resolve()
    scenario = ensure_inputs(pilot, args.experiment1_root.expanduser().resolve())

    print("\nChecking the fixed prepared-workload contract.")
    deploy([
        "--config", scenario,
        "--prepared-workload", pilot / "native/model",
        "--dry-run",
    ])
    if args.prepare_only:
        return

    outdir = pilot / "executions" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir.mkdir(parents=True)
    (outdir / "plan-snapshot.json").write_text(json.dumps(plan, indent=2) + "\n")

    print("\nDeploying/qualifying the fixed three-UE native baseline.")
    baseline = deploy([
        "--config", scenario,
        "--prepared-workload", pilot / "native/model",
    ])
    summary = json.loads((baseline / "summary.json").read_text())
    coverage = summary.get("experimental_coverage", {})
    if coverage.get("transport_loss_observed") is not False:
        die("no-load native baseline did not qualify with zero transport loss")

    lstar, ran, broker, b, dst = calibrate(plan, scenario, baseline, outdir)
    matched_block(plan, scenario, pilot, baseline, outdir, lstar, ran, broker, b, dst)

    print("\nExperiment-2 RFSIM pilot complete.")
    print(f"evidence={outdir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
