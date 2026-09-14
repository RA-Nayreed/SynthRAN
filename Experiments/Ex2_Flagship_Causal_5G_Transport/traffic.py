"""Accepted-testbed SSH and competing-traffic helpers for Experiment 2."""
from __future__ import annotations
import hashlib, json, shlex, subprocess, time
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
    if interface not in process.stdout or f"from {address}" not in process.stdout:
        raise RuntimeError("competing traffic is not routed through its assigned 5G tunnel")
    return process.stdout.strip()


def _sender_command(environment: dict[str, Any], competitor: dict[str, Any], destination: str, *, rate: float, seconds: float, packet_bytes: int, port: int) -> list[str]:
    deployment = environment["deployment"]
    address = str(competitor["address"])
    args = (
        f"python3 /tmp/exp2_udp_sender.py --destination {shlex.quote(destination)} "
        f"--port {port} --bind-address {shlex.quote(address)} "
        f"--rate-mbps {rate:g} --duration-seconds {seconds:g} --packet-bytes {packet_bytes}"
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


def _start_background(environment: dict[str, Any], competitor: dict[str, Any], destination: str, *, rate: float, seconds: float, packet_bytes: int, port: int) -> tuple[subprocess.Popen[str], subprocess.Popen[str]]:
    broker = str(environment["deployment"]["nodes"]["broker"])
    base, target = _ssh_base(environment, broker)
    receiver = subprocess.Popen(
        [
            *base,
            "-n",
            target,
            f"python3 /tmp/exp2_udp_receiver.py --port {port} --startup-timeout-seconds 30 --idle-timeout-seconds 3",
        ],
        cwd=ROOT,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(0.75)
    sender = subprocess.Popen(
        _sender_command(
            environment,
            competitor,
            destination,
            rate=rate,
            seconds=seconds,
            packet_bytes=packet_bytes,
            port=port,
        ),
        cwd=ROOT,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return sender, receiver


def _finish_background(sender: subprocess.Popen[str], receiver: subprocess.Popen[str], timeout: float) -> dict[str, Any]:
    sout, serr = sender.communicate(timeout=timeout)
    rout, rerr = receiver.communicate(timeout=15)
    if sender.returncode:
        raise RuntimeError(f"background sender failed: {serr.strip()}")
    if receiver.returncode:
        raise RuntimeError(f"background receiver failed: {rerr.strip()}")
    tx, rx = _json_line(sout), _json_line(rout)
    sent, received = int(tx["packets_attempted"]), int(rx["packets_received"])
    return {
        "sender": tx,
        "receiver": rx,
        "packets_attempted": sent,
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
