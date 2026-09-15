"""Accepted-testbed SSH and competing-traffic helpers for Experiment 2."""
from __future__ import annotations
import hashlib, json, math, os, queue, shlex, subprocess, threading
from pathlib import Path
from typing import Any
import yaml
from .common import HERE, ROOT, _run

def _inventory_host_vars(environment: dict[str, Any], hostname: str) -> dict[str, Any]:
    private = Path(environment["attachment"]["private_execution_dir"])
    inventory = yaml.safe_load((private / "inventory.yml").read_text(encoding="utf-8")) or {}

    def visit(node: Any) -> dict[str, Any] | None:
        if not isinstance(node, dict):
            return None
        hosts = node.get("hosts")
        if isinstance(hosts, dict) and hostname in hosts:
            value = hosts[hostname]
            return value if isinstance(value, dict) else {}
        children = node.get("children")
        if isinstance(children, dict):
            for child in children.values():
                found = visit(child)
                if found is not None:
                    return found
        return None

    found = visit(inventory.get("all", {}))
    if found is None:
        raise RuntimeError(f"accepted deployment inventory has no host {hostname!r}")
    return found


def _ssh_control_path(environment: dict[str, Any], hostname: str) -> Path:
    """Return a short control socket owned by the accepted deployment context."""
    private = Path(environment["attachment"]["private_execution_dir"])
    directory = private / "ssh"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    token = hashlib.sha256(hostname.encode("utf-8")).hexdigest()[:12]
    return directory / token


def _ssh_base(environment: dict[str, Any], hostname: str, *, scp: bool = False) -> tuple[list[str], str]:
    """Use the exact SSH contract emitted by deploy.sh, with connection reuse."""
    variables = _inventory_host_vars(environment, hostname)
    binary = "scp" if scp else "ssh"
    command = [binary]
    common = str(variables.get("ansible_ssh_common_args", "") or "")
    if common:
        command.extend(shlex.split(common))
    key = variables.get("ansible_ssh_private_key_file")
    if key:
        command.extend(["-i", str(key)])
    command.extend(
        [
            "-o",
            "ControlMaster=auto",
            "-o",
            "ControlPersist=120",
            "-o",
            f"ControlPath={_ssh_control_path(environment, hostname)}",
        ]
    )
    target_host = str(variables.get("ansible_host") or hostname)
    user = variables.get("ansible_user")
    target = f"{user}@{target_host}" if user else target_host
    return command, target


def _ssh(environment: dict[str, Any], hostname: str, remote: str, *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    base, target = _ssh_base(environment, hostname)
    return _run(
        [*base, "-n", target, remote],
        capture=capture,
        check=check,
        display=False,
    )


def _scp(environment: dict[str, Any], hostname: str, source: Path, destination: str) -> None:
    base, target = _ssh_base(environment, hostname, scp=True)
    _run([*base, source, f"{target}:{destination}"], display=False)


def _transport_value(binding: dict[str, Any], key: str) -> Any:
    if key in binding:
        return binding.get(key)
    tunnel = binding.get("tunnel", {})
    return tunnel.get(key) if isinstance(tunnel, dict) else None


def _broker_address(environment: dict[str, Any]) -> str:
    broker = str(environment["deployment"]["nodes"]["broker"])
    process = _ssh(
        environment,
        broker,
        "ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i==\"src\") {print $(i+1); exit}}'",
        capture=True,
    )
    lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"could not determine broker IPv4 address on {broker}")
    return lines[-1]


def _stage_udp_tools(environment: dict[str, Any], competitor: dict[str, Any]) -> None:
    deployment = environment["deployment"]
    broker = str(deployment["nodes"]["broker"])
    ran = str(deployment["nodes"]["ran"])
    _scp(environment, broker, HERE / "udp_receiver.py", "/tmp/exp2_udp_receiver.py")
    if deployment["platform"] == "r2lab":
        host = str(_transport_value(competitor, "host") or competitor["device"])
        _scp(environment, host, HERE / "udp_sender.py", "/tmp/exp2_udp_sender.py")
        return
    _scp(environment, ran, HERE / "udp_sender.py", "/tmp/exp2_udp_sender.py")
    namespace = str(_transport_value(competitor, "namespace") or "")
    pod = str(competitor.get("pod") or competitor.get("pod_name") or "")
    container = str(competitor.get("container") or "synthran-runtime")
    if not namespace or not pod:
        raise RuntimeError("software-UE live evidence lacks namespace/pod information")
    remote = (
        f"kubectl cp -n {shlex.quote(namespace)} -c {shlex.quote(container)} "
        f"/tmp/exp2_udp_sender.py {shlex.quote(pod)}:/tmp/exp2_udp_sender.py"
    )
    _ssh(environment, ran, remote)


def _prove_competitor_route(environment: dict[str, Any], competitor: dict[str, Any], destination: str) -> str:
    deployment = environment["deployment"]
    address = str(competitor.get("address") or "")
    interface = str(_transport_value(competitor, "interface") or "")
    if not address or not interface:
        raise RuntimeError("competing UE live evidence lacks address/interface")
    if deployment["platform"] == "r2lab":
        host = str(_transport_value(competitor, "host") or competitor["device"])
        process = _ssh(
            environment,
            host,
            f"ip route get {shlex.quote(destination)} from {shlex.quote(address)}",
            capture=True,
        )
    else:
        ran = str(deployment["nodes"]["ran"])
        namespace = str(_transport_value(competitor, "namespace") or "")
        pod = str(competitor.get("pod") or competitor.get("pod_name") or "")
        container = str(competitor.get("container") or "synthran-runtime")
        remote = (
            f"kubectl exec -n {shlex.quote(namespace)} {shlex.quote(pod)} "
            f"-c {shlex.quote(container)} -- "
            f"ip route get {shlex.quote(destination)} from {shlex.quote(address)}"
        )
        process = _ssh(environment, ran, remote, capture=True)
    tokens = process.stdout.split()
    if not any(tokens[index:index + 2] == ["dev", interface] for index in range(len(tokens))) or not any(
        tokens[index:index + 2] == ["from", address] for index in range(len(tokens))
    ):
        raise RuntimeError("competing traffic is not routed through its assigned 5G tunnel")
    return process.stdout.strip()


def _sender_command(environment: dict[str, Any], competitor: dict[str, Any], destination: str, *, rate: float, seconds: float, packet_bytes: int, port: int) -> list[str]:
    deployment = environment["deployment"]
    address = str(competitor["address"])
    args = (
        f"python3 /tmp/exp2_udp_sender.py --destination {shlex.quote(destination)} "
        f"--port {port} --bind-address {shlex.quote(address)} "
        f"--rate-mbps {rate:g} --duration-seconds {seconds:g} --packet-bytes {packet_bytes} --report-ready"
    )
    if deployment["platform"] == "r2lab":
        host = str(_transport_value(competitor, "host") or competitor["device"])
        base, target = _ssh_base(environment, host)
        return [*base, "-n", target, args]
    ran = str(deployment["nodes"]["ran"])
    namespace = str(_transport_value(competitor, "namespace") or "")
    pod = str(competitor.get("pod") or competitor.get("pod_name") or "")
    container = str(competitor.get("container") or "synthran-runtime")
    remote = (
        f"kubectl exec -n {shlex.quote(namespace)} {shlex.quote(pod)} "
        f"-c {shlex.quote(container)} -- {args}"
    )
    base, target = _ssh_base(environment, ran)
    return [*base, "-n", target, remote]


def _json_line(text: str) -> dict[str, Any]:
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError("expected JSON output was not found")


class ProbeError(RuntimeError):
    """A probe failure with the raw evidence collected before failure."""

    def __init__(self, message: str, evidence: dict[str, Any]):
        super().__init__(message)
        self.evidence = evidence


def _await_ready(process: subprocess.Popen[str], event: str, timeout: float = 30.0) -> None:
    """Wait for an explicit flushed event without buffering later result bytes.

    Reading one byte from the pipe in a bounded daemon thread also works on
    Windows, where select() cannot wait on subprocess pipes. No further reader
    remains after the event, so communicate() exclusively owns final output.
    """
    result: queue.Queue[str | Exception] = queue.Queue()

    def read() -> None:
        try:
            line = bytearray()
            while True:
                byte = os.read(process.stdout.fileno(), 1)
                if not byte:
                    raise RuntimeError(f"process exited before {event}")
                line.extend(byte)
                if byte != b"\n":
                    continue
                text = line.decode("utf-8", errors="replace")
                process._ex2_startup_output = getattr(process, "_ex2_startup_output", "") + text
                line.clear()
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and value.get("event") == event:
                    result.put(event)
                    return
        except Exception as error:
            result.put(error)

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    try:
        outcome = result.get(timeout=timeout)
    except queue.Empty as error:
        raise RuntimeError(f"timed out waiting for {event}") from error
    if isinstance(outcome, Exception):
        raise outcome
    thread.join()


def _stop_background(*processes: subprocess.Popen[str]) -> dict[str, Any]:
    evidence = {}
    for index, process in enumerate(processes):
        if process.poll() is None:
            process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
        evidence[f"process_{index}"] = {
            "returncode": process.returncode,
            "stdout": getattr(process, "_ex2_startup_output", "") + stdout,
            "stderr": stderr,
        }
    return evidence


def _probe_quality(probe: dict[str, Any], config: dict[str, Any], *, rate: float) -> dict[str, Any]:
    """Qualify generator fidelity separately from end-to-end UDP delivery."""
    sender = probe.get("sender", {})
    reasons = []
    def number(value: Any) -> float:
        try:
            return float(value) if not isinstance(value, bool) else math.nan
        except (TypeError, ValueError):
            return math.nan

    actual = number(sender.get("actual_payload_mbps"))
    requested = number(sender.get("requested_payload_mbps"))
    if not math.isfinite(requested) or not math.isclose(requested, rate, rel_tol=1e-9, abs_tol=1e-9):
        reasons.append("sender_requested_rate_differs_from_frozen_load")
    fraction = actual / rate
    lower = float(config["achieved_rate_fraction_min"])
    upper = float(config["achieved_rate_fraction_max"])
    if not math.isfinite(fraction) or not lower <= fraction <= upper:
        reasons.append("achieved_payload_rate_outside_prespecified_bounds")
    if number(sender.get("send_errors")) != 0:
        reasons.append("local_sender_errors")
    sent = number(sender.get("packets_sent"))
    received = number(probe.get("packets_received"))
    if not math.isfinite(sent) or sent <= 0 or sent != int(sent) or number(sender.get("packets_attempted")) != sent:
        reasons.append("invalid_sender_packet_accounting")
    if not math.isfinite(received) or not 0 <= received <= sent or received != int(received):
        reasons.append("invalid_receiver_packet_accounting")
    ratio = number(probe.get("delivery_ratio"))
    if not math.isfinite(ratio) or not 0 <= ratio <= 1 or (
        sent > 0 and not math.isclose(ratio, received / sent, abs_tol=1e-12, rel_tol=1e-12)
    ):
        reasons.append("invalid_delivery_ratio")
    return {
        "valid": not reasons,
        "reasons": reasons,
        "actual_rate_fraction": fraction if math.isfinite(fraction) else None,
        "achieved_rate_fraction_min": lower,
        "achieved_rate_fraction_max": upper,
    }


def _start_background(environment: dict[str, Any], competitor: dict[str, Any], destination: str, *, rate: float, seconds: float, packet_bytes: int, port: int) -> tuple[subprocess.Popen[str], subprocess.Popen[str]]:
    broker = str(environment["deployment"]["nodes"]["broker"])
    base, target = _ssh_base(environment, broker)
    receiver = subprocess.Popen(
        [
            *base,
            "-n",
            target,
            f"python3 /tmp/exp2_udp_receiver.py --bind {shlex.quote(destination)} --port {port} "
            "--startup-timeout-seconds 30 --idle-timeout-seconds 3 --report-ready",
        ],
        cwd=ROOT,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    sender = None
    try:
        _await_ready(receiver, "receiver_ready")
        sender = subprocess.Popen(
            _sender_command(
                environment, competitor, destination, rate=rate, seconds=seconds,
                packet_bytes=packet_bytes, port=port,
            ),
            cwd=ROOT, text=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        _await_ready(sender, "sender_started")
    except Exception as error:
        evidence = _stop_background(*([sender, receiver] if sender is not None else [receiver]))
        raise ProbeError(f"UDP probe startup failed: {error}", evidence) from error
    return sender, receiver


def _finish_background(sender: subprocess.Popen[str], receiver: subprocess.Popen[str], timeout: float) -> dict[str, Any]:
    sout = serr = rout = rerr = ""
    try:
        sout, serr = sender.communicate(timeout=timeout)
        rout, rerr = receiver.communicate(timeout=35)
    except subprocess.TimeoutExpired as error:
        evidence = _stop_background(sender, receiver)
        evidence["already_collected"] = {"sender_stdout": sout, "sender_stderr": serr, "receiver_stdout": rout, "receiver_stderr": rerr}
        raise ProbeError("UDP probe timed out", evidence) from error
    raw = {
        "sender_stdout": getattr(sender, "_ex2_startup_output", "") + sout,
        "sender_stderr": serr,
        "receiver_stdout": getattr(receiver, "_ex2_startup_output", "") + rout,
        "receiver_stderr": rerr,
    }
    if sender.returncode or receiver.returncode:
        raise ProbeError("background UDP process failed", raw)
    try:
        tx, rx = _json_line(sout), _json_line(rout)
        sent, received = int(tx["packets_sent"]), int(rx["packets_received"])
        attempted = int(tx["packets_attempted"])
    except (RuntimeError, KeyError, TypeError, ValueError) as error:
        raise ProbeError(f"invalid UDP probe output: {error}", raw) from error
    return {
        "sender": tx,
        "receiver": rx,
        "packets_attempted": attempted,
        "packets_sent": sent,
        "packets_received": received,
        "packets_lost": max(sent - received, 0),
        "delivery_ratio": received / sent if sent else 0.0,
    }


def _udp_probe(environment: dict[str, Any], competitor: dict[str, Any], destination: str, *, rate: float, seconds: float, packet_bytes: int, port: int) -> dict[str, Any]:
    sender, receiver = _start_background(
        environment,
        competitor,
        destination,
        rate=rate,
        seconds=seconds,
        packet_bytes=packet_bytes,
        port=port,
    )
    return _finish_background(sender, receiver, seconds + 30)
