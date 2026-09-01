#!/usr/bin/env python3
"""Discover UE tunnels and the containers that own them."""
import json
import re
import subprocess

pattern = re.compile(r"^(tun_srsue\d+|uesimtun\d*|oaitun_[A-Za-z0-9_.-]+)$")
pods = json.loads(subprocess.check_output([
    "kubectl", "get", "pods", "--all-namespaces",
    "--field-selector=status.phase=Running", "-o", "json",
], text=True))
found = []
for pod in pods["items"]:
    namespace, name = pod["metadata"]["namespace"], pod["metadata"]["name"]
    for container in pod["spec"].get("containers", []):
        cname = container["name"]
        command = ["kubectl", "exec", "-n", namespace, name, "-c", cname, "--", "ip", "-o", "link", "show"]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            continue
        for line in result.stdout.splitlines():
            interface = line.split(":", 2)[1].strip().split("@", 1)[0]
            if pattern.match(interface):
                address_cmd = ["kubectl", "exec", "-n", namespace, name, "-c", cname, "--", "ip", "-4", "-o", "addr", "show", "dev", interface]
                address_output = subprocess.run(address_cmd, text=True, capture_output=True)
                addresses = re.findall(r"\binet\s+([0-9.]+)/", address_output.stdout)
                if addresses:
                    found.append({"namespace": namespace, "pod": name, "container": cname, "interface": interface, "address": addresses[0]})

def natural(item):
    return (item["namespace"], item["pod"], [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", item["interface"])])
print(json.dumps(sorted(found, key=natural)))
