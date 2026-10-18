"""Container acceptance for deploy/compose.yaml on a Linux Docker host (CI job "container").

Usage: python3 scripts/container_check.py IMAGE [--emulated]

Runs the unmodified Compose file (only the image, config and secrets paths come from
the environment) against a throwaway bridge network whose host-side interface plays
the part of dragon's eth0, then proves:

1. The worker service, as UID 10001 with only NET_RAW in its bounding set, runs
   scanner.process.execute() (the exact `-n -e IFACE -sn -PR --send-eth --privileged`
   arguments) and finds the idle targets with their MAC addresses.
2. The same scan fails without NET_RAW and with no-new-privileges, so both settings
   are load-bearing.
3. The web service runs with zero capabilities and no-new-privileges, and its
   healthcheck turns healthy.
4. Requests carrying tailscale serve's headers from 127.0.0.1 pass the same-origin
   mutation check; the same request without X-Forwarded-Proto is rejected.
5. End to end: a live network created through the API is discovered by the
   scheduled worker, and the targets appear as devices with their MACs.

--emulated (job "arm64", QEMU user mode on an x86 kernel): QEMU does not translate
the SIOCETHTOOL ioctl that psutil's net_if_stats() issues, so step 1 calls
scanner.process.arguments() and route_health() and runs nmap itself instead of
execute(), and step 5 stops after creating the network.

Standard library only; needs Docker with the Compose plugin and must run as a user
that can create bridge networks. Leaves nothing behind.
"""

import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "ndci"
BRIDGE, IFACE, SUBNET = "ndci-scan", "ndscan0", "172.30.99.0/24"
TARGETS = {"ndci-target-1": "172.30.99.10", "ndci-target-2": "172.30.99.11"}
PUBLIC = "dragon.lonk-dorian.ts.net:8443"
PASSWORD = "container-check-password"
NET_RAW = 1 << 13

SCAN = """
import json, os, re, subprocess, sys, types
from network_dragon.config import Config
from network_dragon.scanner import process
cidr, iface, emulated = sys.argv[1], sys.argv[2], sys.argv[3] == "emulated"
status = open("/proc/self/status").read()
caps = dict(re.findall(r"^(Cap\\w+|NoNewPrivs):\\s+(\\w+)$", status, re.M))
print(json.dumps({"uid": os.getuid(), "status": caps}), flush=True)
config = Config(live_scanning=True, allowed_cidrs=[cidr], allowed_interfaces=[iface])
network = types.SimpleNamespace(mode="live", enabled=True, cidr=cidr, interface=iface)
profile = types.SimpleNamespace(kind="discovery", budget=config.discovery_seconds)
if emulated:
    # QEMU user mode does not translate psutil's SIOCETHTOOL ioctl, so skip only
    # interface_health; the arguments and route check are the worker's own.
    args = process.arguments(config, network, profile, cidr)
    process.route_health(network, cidr)
    result = subprocess.run(args, capture_output=True, start_new_session=True)
    if result.returncode:
        sys.exit(f"nmap exit {result.returncode}: {result.stderr.decode()[-500:]}")
    data = result.stdout
else:
    data, args = process.execute(config, network, profile, cidr)
macs = re.findall(rb'addr="([0-9A-Fa-f:]{17})" addrtype="mac"', data)
print(json.dumps({"args": args, "macs": [m.decode().lower() for m in macs]}))
"""


def log(message):
    print(f"\n=== {message}", flush=True)


def run(*args, check=True, input=None, env=None):
    result = subprocess.run(args, capture_output=True, text=True, input=input, env=env, timeout=600)
    if check and result.returncode:
        raise SystemExit(
            f"FAILED ({result.returncode}): {' '.join(args)}\n{result.stdout}\n{result.stderr}"
        )
    return result


def check(condition, message):
    if not condition:
        raise SystemExit(f"ASSERTION FAILED: {message}")
    print(f"ok: {message}", flush=True)


def caps(status_text):
    return dict(re.findall(r"^(Cap\w+|NoNewPrivs):\s+(\w+)$", status_text, re.M))


def call(method, path, headers=None, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.getheader("set-cookie") or "", response.read()
    finally:
        connection.close()


def main(image, emulated=False):
    mode = "emulated" if emulated else "native"
    work = Path(tempfile.mkdtemp(prefix="ndci-"))
    secrets = work / "secrets"
    secrets.mkdir()
    for name in ["pushover_token", "pushover_user"]:
        (secrets / name).write_text("")
    config = work / "config.toml"
    template = (ROOT / "deploy/config.dragon.example.toml").read_text(encoding="utf-8")
    config.write_text(
        template.replace("live_scanning = false", "live_scanning = true")
        .replace('"192.168.30.0/24"', f'"{SUBNET}"')
        .replace('["eth0"]', f'["{IFACE}"]')
        .replace("discovery_seconds = 120", "discovery_seconds = 30"),
        encoding="utf-8",
    )
    for path in [work, secrets, *secrets.iterdir(), config]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    env = {
        **os.environ,
        "NETWORK_DRAGON_IMAGE": image,
        "NETWORK_DRAGON_CONFIG_FILE": str(config),
        "NETWORK_DRAGON_SECRETS_DIR": str(secrets),
    }
    compose = ["docker", "compose", "-f", str(ROOT / "deploy/compose.yaml"), "-p", PROJECT]

    def dc(*args, **kwargs):
        return run(*compose, *args, env=env, **kwargs)

    try:
        log("Image facts")
        facts = run(
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            image,
            "-c",
            "import os, shutil, subprocess\n"
            "print(os.getuid(), os.getgid())\n"
            "print(os.getxattr('/usr/bin/nmap', 'security.capability').hex())\n"
            "print(subprocess.run(['find', '/', '-xdev', '-type', 'f', '-perm', '/6000'],"
            " capture_output=True, text=True).stdout.strip() or 'none')\n"
            "print(shutil.which('ip'))\n"
            "print(subprocess.run(['nmap', '--version'], capture_output=True, text=True).stdout.splitlines()[0])",
        ).stdout.splitlines()
        print("\n".join(facts))
        check(facts[0] == "10001 10001", "image runs as UID/GID 10001")
        xattr = bytes.fromhex(facts[1])
        permitted, inheritable = (int.from_bytes(xattr[i : i + 4], "little") for i in (4, 8))
        check(
            xattr[0] & 1 and permitted == NET_RAW and inheritable == 0,
            "nmap carries exactly cap_net_raw+ep",
        )
        check(facts[2] == "none", "no setuid/setgid files in the image")
        check(facts[3] != "None", "iproute2's ip (route verification) is installed")

        log(f"Bridge {BRIDGE} ({IFACE}, {SUBNET}) with idle targets")
        run(
            "docker",
            "network",
            "create",
            "--subnet",
            SUBNET,
            "-o",
            f"com.docker.network.bridge.name={IFACE}",
            BRIDGE,
        )
        macs = {}
        for name, ip in TARGETS.items():
            run(
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                name,
                "--network",
                BRIDGE,
                "--ip",
                ip,
                "--read-only",
                "--cap-drop",
                "ALL",
                "--entrypoint",
                "sleep",
                image,
                "infinity",
            )
            macs[
                run(
                    "docker",
                    "inspect",
                    "-f",
                    f'{{{{(index .NetworkSettings.Networks "{BRIDGE}").MacAddress}}}}',
                    name,
                )
                .stdout.strip()
                .lower()
            ] = ip
        print(json.dumps(macs))

        log("1. Worker service scans with its Compose settings")
        result = dc(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "python",
            "worker",
            "-c",
            SCAN,
            SUBNET,
            IFACE,
            mode,
            check=False,
        )
        print(result.stdout, result.stderr, sep="\n")
        arp = result.returncode == 0 or not emulated
        if not arp:
            # Diagnose, do not prove: under QEMU user mode nmap runs inside the
            # qemu-aarch64 interpreter on the x86 runner's kernel. Root with NET_RAW
            # separates "file capability not applied through binfmt" from "QEMU
            # cannot emulate the raw-socket path". The native job is the ARP proof.
            control = run(
                "docker",
                "run",
                "--rm",
                "--network",
                "host",
                "--user",
                "0:0",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "NET_RAW",
                "--entrypoint",
                "python",
                image,
                "-c",
                SCAN,
                SUBNET,
                IFACE,
                mode,
                check=False,
            )
            print("root + NET_RAW control:", control.returncode, control.stdout, control.stderr)
            print(
                "NOT PROVEN under emulation: ARP discovery as UID 10001. Steps 1-2 skipped;"
                " the native 'container' job proves them and dragon runs nmap natively."
            )
        else:
            check(result.returncode == 0, "worker discovery scan exits cleanly")
        if arp:
            first, second = (json.loads(line) for line in result.stdout.strip().splitlines()[-2:])
            status = first["status"]
            check(first["uid"] == 10001, "scan runs as UID 10001")
            check(int(status["CapBnd"], 16) == NET_RAW, "worker bounding set is exactly NET_RAW")
            check(
                int(status["CapEff"], 16) == int(status["CapPrm"], 16) == 0,
                "the Python worker itself holds no capabilities",
            )
            check(status["NoNewPrivs"] == "0", "worker runs without no-new-privileges")
            args = second["args"]
            check(
                args[:8] == ["nmap", "-n", "-e", IFACE, "-sn", "-PR", "--send-eth", "--privileged"]
                and args[-3:] == ["-oX", "-", SUBNET],
                f"scanner.process arguments: {' '.join(args)}",
            )
            check(set(macs) <= set(second["macs"]), f"targets found with MACs {sorted(macs)}")

            log("2. Negative controls (plain docker run, otherwise identical)")
            base = [
                "docker",
                "run",
                "--rm",
                "--network",
                "host",
                "--user",
                "10001:10001",
                "--read-only",
                "--tmpfs",
                "/tmp:size=32m,mode=1777",
                "--cap-drop",
                "ALL",
            ]
            for label, extra in [
                ("without NET_RAW", []),
                (
                    "with no-new-privileges",
                    ["--cap-add", "NET_RAW", "--security-opt", "no-new-privileges:true"],
                ),
            ]:
                result = run(
                    *base,
                    *extra,
                    "--entrypoint",
                    "python",
                    image,
                    "-c",
                    SCAN,
                    SUBNET,
                    IFACE,
                    mode,
                    check=False,
                )
                tail = (result.stderr.strip().splitlines() or [""])[-1]
                print(f"{label}: exit {result.returncode}: {tail}")
                check(result.returncode != 0, f"discovery fails {label}")

        log("Initialize data volume and administrator")
        print(dc("run", "--rm", "--no-deps", "-T", "web", "init").stdout)
        print(
            dc(
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "web",
                "create-admin",
                input=f"{PASSWORD}\n{PASSWORD}\n",
            ).stdout
        )
        dc("up", "-d")

        log("3. Web service: healthcheck and capabilities")
        deadline = time.monotonic() + 120
        while True:
            health = run(
                "docker", "inspect", "-f", "{{.State.Health.Status}}", f"{PROJECT}-web-1"
            ).stdout.strip()
            if health == "healthy" or time.monotonic() > deadline:
                break
            time.sleep(2)
        check(health == "healthy", "web healthcheck reports healthy")
        for service, bounding, nnp in [("web", 0, "1"), ("worker", NET_RAW, "0")]:
            status = caps(dc("exec", "-T", service, "cat", "/proc/1/status").stdout)
            print(service, status)
            check(
                int(status["CapEff"], 16) == int(status["CapPrm"], 16) == 0
                and int(status["CapBnd"], 16) == bounding
                and status["NoNewPrivs"] == nnp,
                f"{service}: no effective capabilities, bounding {bounding:#x}, NoNewPrivs {nnp}",
            )
            inspect = json.loads(run("docker", "inspect", f"{PROJECT}-{service}-1").stdout)[0]
            host = inspect["HostConfig"]
            check(
                host["ReadonlyRootfs"]
                and host["NetworkMode"] == "host"
                and host["PidsLimit"] == 100
                and host["Memory"] == 256 * 1024 * 1024
                and host["LogConfig"]["Config"] == {"max-file": "3", "max-size": "10m"}
                and "TZ=America/New_York" in inspect["Config"]["Env"],
                f"{service}: read-only, host network, pids/memory/log limits, TZ",
            )
        # The web container shares the host network namespace, so its ss sees the host.
        listeners = dc("exec", "-T", "web", "ss", "-Htln", "sport = :8000").stdout
        print(listeners)
        check(
            listeners.strip()
            and all(" 127.0.0.1:8000 " in f" {line} " for line in listeners.splitlines()),
            "web listens on 127.0.0.1:8000 only",
        )

        log("4. tailscale serve headers and the origin check")
        serve = {
            "Host": PUBLIC,
            "X-Forwarded-Host": PUBLIC,
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": "100.101.102.103",
            "Origin": f"https://{PUBLIC}",
            "Content-Type": "application/json",
        }
        login = json.dumps({"password": PASSWORD})
        plain = {k: v for k, v in serve.items() if k != "X-Forwarded-Proto"}
        status, _, body = call("POST", "/api/v1/session", plain, login)
        check(status == 403 and b"Cross-origin" in body, "without X-Forwarded-Proto: 403")
        status, cookie, body = call("POST", "/api/v1/session", serve, login)
        check(status == 200 and "Secure" in cookie, "with tailscale serve headers: signed in")
        session = {
            **serve,
            "Cookie": cookie.split(";", 1)[0],
            "X-CSRF-Token": json.loads(body)["csrf"],
        }

        log("5. Live network through the API, discovered by the scheduled worker")
        status, _, body = call(
            "POST",
            "/api/v1/networks",
            session,
            json.dumps({"name": "CI bridge", "cidr": SUBNET, "interface": IFACE, "mode": "live"}),
        )
        check(status == 200, f"live network created: {body.decode()[:200]}")
        if emulated:
            print("skipped under emulation: the scheduled job runs interface_health (psutil)")
            print("\nAll container checks passed (emulated).")
            return
        deadline = time.monotonic() + 180
        while True:
            _, _, body = call("GET", "/api/v1/devices?limit=100", session)
            found = {d["mac"].lower(): d["ip"] for d in json.loads(body)["items"] if d.get("mac")}
            if set(macs) <= set(found) or time.monotonic() > deadline:
                break
            time.sleep(3)
        _, _, scans = call("GET", "/api/v1/scans?limit=5", session)
        for job in json.loads(scans)["jobs"]["items"]:
            print(job["profile_id"], job["target"], job["status"], job["error"])
        print(json.dumps(found))
        check(
            all(found.get(mac) == ip for mac, ip in macs.items()),
            "worker discovered both targets with MAC and IP",
        )

        log("Resource use")
        print(
            run(
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.Name}} mem={{.MemUsage}} pids={{.PIDs}}",
            ).stdout
        )
        print("\nAll container checks passed.")
    except BaseException:
        print(dc("logs", "--no-color", check=False).stdout[-20000:])
        raise
    finally:
        dc("down", "-v", "--remove-orphans", check=False)
        for name in TARGETS:
            run("docker", "rm", "-f", name, check=False)
        run("docker", "network", "rm", BRIDGE, check=False)


if __name__ == "__main__":
    main(sys.argv[1], emulated="--emulated" in sys.argv[2:])
