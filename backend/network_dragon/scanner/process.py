import ipaddress
import json
import os
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import psutil

from network_dragon.scanner.validation import excluded, ports, validate_live
from network_dragon.scanner.xml import MAX_XML


def interface_health(network):
    stats = psutil.net_if_stats().get(network.interface)
    if not stats or not stats.isup:
        raise ValueError("Configured interface is missing or down")
    scope = ipaddress.IPv4Network(network.cidr)
    addresses = psutil.net_if_addrs().get(network.interface, [])
    for address in addresses:
        if address.family == socket.AF_INET and address.netmask:
            link = ipaddress.IPv4Network(f"{address.address}/{address.netmask}", strict=False)
            if scope.subnet_of(link):
                return
    raise ValueError("Configured scope is not on-link on the selected interface")


def route_health(network, target):
    own_addresses = {
        a.address
        for a in psutil.net_if_addrs().get(network.interface, [])
        if a.family == socket.AF_INET
    }
    address = next(
        (str(a) for a in ipaddress.IPv4Network(target).hosts() if str(a) not in own_addresses), None
    )
    if address is None:
        raise ValueError("Scanning the scanner's own address is unsupported")
    try:
        result = subprocess.run(
            ["ip", "-j", "route", "get", address], capture_output=True, timeout=3, check=True
        )
        routes = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError("Could not verify the selected interface route") from exc
    if not routes or routes[0].get("dev") != network.interface or routes[0].get("gateway"):
        raise ValueError("Target route does not use the configured on-link interface")


def arguments(config, network, profile, target):
    validate_live(target, network, config)
    args = [config.nmap, "-n", "-e", network.interface]
    if profile.kind == "discovery":
        args += ["-sn", "-PR", "--send-eth", "--privileged"]
        if skipped := excluded(config, target):
            args += ["--exclude", ",".join(skipped)]
    else:
        if ipaddress.ip_network(target).num_addresses != 1:
            raise ValueError("Port jobs must target one previously discovered address")
        args += ["-sT", "-Pn"]
        if profile.ports == "top1000":
            args += ["--top-ports", "1000"]
        else:
            ports(profile.ports)
            args += ["-p", profile.ports]
        if profile.enrichment:
            args += ["-sV", "--version-light"]
    return args + ["--host-timeout", f"{profile.budget}s", "-oX", "-", target]


def terminate(process):
    if process.poll() is not None:
        return
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=3)


def execute(config, network, profile, target, cancelled=lambda: False):
    args = arguments(config, network, profile, target)
    if os.name != "posix":
        raise ValueError("Live execution is supported only on validated Linux deployments")
    interface_health(network)
    route_health(network, target)
    with tempfile.TemporaryDirectory(prefix="network-dragon-") as directory:
        output, errors = Path(directory) / "scan.xml", Path(directory) / "stderr"
        with output.open("wb") as stdout, errors.open("wb") as stderr:
            process = subprocess.Popen(
                args, stdout=stdout, stderr=stderr, shell=False, start_new_session=True
            )
            deadline = time.monotonic() + profile.budget + 5
            try:
                while process.poll() is None:
                    if cancelled():
                        raise ValueError("Scan cancelled or worker lease lost")
                    if time.monotonic() >= deadline:
                        raise ValueError("Scan deadline exceeded")
                    if output.stat().st_size > MAX_XML or errors.stat().st_size > 65536:
                        raise ValueError("Scan output limit exceeded")
                    time.sleep(0.1)
                if process.returncode:
                    raise ValueError(
                        f"Nmap failed with exit code {process.returncode}; no absence evidence applied"
                    )
            finally:
                terminate(process)
        interface_health(network)
        route_health(network, target)
        data = output.read_bytes()
        if len(data) > MAX_XML:
            raise ValueError("Scan output limit exceeded")
        return data, args
