# Deploying on dragon

Runbook for **dragon**: Raspberry Pi 4 (2 GB), Raspberry Pi OS Lite 64-bit (Debian 13 trixie, aarch64), Docker 26.1.5 from Debian's `docker.io`. It monitors one network, VLAN 30 (AI-Zone), on `eth0` (192.168.30.123/24). Bluehood already uses host networking on 127.0.0.1:8080 and `tailscale serve` already uses HTTPS port 443, so Network Dragon uses **127.0.0.1:8000** locally and **https://dragon.lonk-dorian.ts.net:8443** on the tailnet.

Files on the Pi:

| Path | Contents | Owner / mode |
| --- | --- | --- |
| `/opt/network-dragon/compose.yaml` | copy of `deploy/compose.yaml` | root, 0644 |
| `/opt/network-dragon/.env` | `NETWORK_DRAGON_IMAGE=...` (the pinned image) | root, 0644 |
| `/etc/network-dragon/config.toml` | from `deploy/config.dragon.example.toml` | root:10001, 0640 |
| `/etc/network-dragon/secrets/` | `pushover_token`, `pushover_user` (empty until delivery) | root:10001, 0750 / 0640 |
| Docker volume `network-dragon_dragon-data` | SQLite database and `backups/` | 10001:10001 |

Both containers use the host network namespace. The web service binds 127.0.0.1:8000 only, has no capabilities and runs with `no-new-privileges`. The worker runs as UID 10001 with `cap_drop: [ALL]` and `cap_add: [NET_RAW]`. Nmap in the image carries the file capability `cap_net_raw+ep`, so only nmap gets raw sockets; the Python worker holds no capabilities. `no-new-privileges` is left off for the worker because it would stop that file capability from taking effect when the worker runs nmap. To make up for that, the image has no setuid or setgid files. NET_ADMIN is not needed. Both services have a read-only root filesystem, a 32 MB `/tmp` tmpfs, `pids_limit: 100`, `mem_limit: 256m`, json-file logs capped at 3 × 10 MB, and `TZ=America/New_York`.

## What CI proves and what it does not

Every pull request runs `scripts/container_check.py` against the image built from that commit, once natively on amd64 (job `container`) and once as linux/arm64 under QEMU (job `arm64`). The script runs this Compose file unchanged, against a Docker bridge whose host-side interface stands in for `eth0`, and checks that:

- the worker service runs the real `scanner.process.execute()` with the exact arguments (`nmap -n -e <iface> -sn -PR --send-eth --privileged --host-timeout 120s -oX - <cidr>`) as UID 10001 and finds the idle target containers with their MAC addresses;
- the same scan fails without NET_RAW, and fails with `no-new-privileges`;
- the web container has empty effective, permitted and bounding capability sets, its healthcheck turns healthy, and it listens on 127.0.0.1:8000 only;
- a sign-in carrying `tailscale serve`'s headers from 127.0.0.1 passes the same-origin check and gets a `Secure` cookie, while the same request without `X-Forwarded-Proto` gets 403;
- a live network created through the API is picked up by the scheduled worker, and both targets appear as devices with the right MAC and IP.

The `arm64` job runs with `--emulated`, and it does **not** prove ARP on arm64. Under QEMU user mode, nmap runs inside an emulator on the runner's x86 kernel, and its raw-device path fails ("Failed to open device"). It fails the same way as root with NET_RAW effective, so the cause is the emulation, not the capability set. QEMU also lacks psutil's SIOCETHTOOL ioctl. The arm64 job does prove the following on the arm64 image:

- uid and gid are 10001
- nmap carries `cap_net_raw+ep`
- there are no setuid or setgid files
- nmap and `ip` run
- `init` and `create-admin` work on the named volume
- the web container's capabilities, healthcheck and loopback-only bind are correct
- the tailscale-serve origin flow works
- a live network can be created through the API

ARP as UID 10001 on arm64 is checked in step 6 on dragon itself.

`tests/test_proxy_origin.py` covers the proxy behaviour again outside containers.

These things have **not** been proven and must be checked on dragon:

- That Docker 26.1.5 on the Pi keeps nmap's file capability when it pulls the image (step 2 checks this).
- That memory limits are enforced. Raspberry Pi kernels often ship with the memory cgroup off (step 1).
- ARP on arm64 at all, and on the real `eth0` and VLAN 30 through the physical switch rather than a Linux bridge. ARP was proven natively on amd64 only.
- The real `tailscale serve` on dragon, and running alongside Bluehood for memory and ports.
- The Debian `docker-compose` package version and its Compose features (step 1).
- Firewall, IPv6 policy, and Pushover delivery (see the end of this page).

## 1. Install the Compose plugin and check the host

```sh
sudo apt update
sudo apt install docker-compose   # Debian's package; in trixie it ships the Compose v2 CLI plugin
docker compose version            # must print "Docker Compose version v2.x"
```

If `docker compose` is still missing, install the static plugin from the [Compose releases](https://github.com/docker/compose/releases) as `/usr/local/lib/docker/cli-plugins/docker-compose` (the `linux-aarch64` asset) and make it executable.

Check memory-limit support and the ports:

```sh
docker info 2>&1 | grep -i -E 'cgroup|memory limit'   # any "No memory limit support" warning means limits are ignored
sudo ss -tlnp | grep -E ':(8000|8443)\b'              # must print nothing
```

If Docker warns about memory limits, add `cgroup_enable=memory` to the single line in `/boot/firmware/cmdline.txt`, reboot, and check again.

## 2. Pull the image

The image is published by CI from `main` as `ghcr.io/dq-labs/network-dragon:sha-<commit>` and `:latest`, for linux/arm64 and linux/amd64. Pin a `sha-` tag:

```sh
sudo mkdir -p /opt/network-dragon /etc/network-dragon/secrets
sudo cp deploy/compose.yaml /opt/network-dragon/compose.yaml          # from a checkout of the same commit
echo 'NETWORK_DRAGON_IMAGE=ghcr.io/dq-labs/network-dragon:sha-XXXXXXX' | sudo tee /opt/network-dragon/.env
cd /opt/network-dragon
sudo docker compose pull
sudo docker image inspect --format '{{index .RepoDigests 0}}' "$(sudo docker compose config --images | head -1)"   # record this digest
```

Check that the pull kept nmap's file capability (`0100000200200000...` means `cap_net_raw+ep`):

```sh
sudo docker compose run --rm --no-deps --entrypoint python worker \
  -c "import os; print(os.getxattr('/usr/bin/nmap', 'security.capability').hex())"
```

If the package is still private, either have the owner make it public (GitHub → the org's **Packages** → `network-dragon` → **Package settings** → **Change visibility**) or run `docker login ghcr.io` with a token that has `read:packages`.

## 3. Configure, `init` and `create-admin`

```sh
sudo cp deploy/config.dragon.example.toml /etc/network-dragon/config.toml
sudo touch /etc/network-dragon/secrets/pushover_token /etc/network-dragon/secrets/pushover_user
sudo chown -R root:10001 /etc/network-dragon
sudo chmod 0640 /etc/network-dragon/config.toml /etc/network-dragon/secrets/*
sudo chmod 0750 /etc/network-dragon/secrets
```

The app reads `PUSHOVER_TOKEN_FILE`/`PUSHOVER_USER_FILE` when needed; an empty or missing file means "not configured", and the Settings page says so. The template starts with `live_scanning = false` and `notifications = false`, with the VLAN 30 allowlist, `eth0`, and `trusted_proxy_ips = ["127.0.0.1"]` already filled in.

```sh
cd /opt/network-dragon
sudo docker compose run --rm --no-deps web init
sudo docker compose run --rm --no-deps web create-admin    # interactive; 12+ characters
```

## 4. First start, with live scanning off

```sh
sudo docker compose up -d
sudo docker compose ps                         # web "healthy", worker "running"
curl -fsS http://127.0.0.1:8000/health/ready   # {"status":"ready"}
sudo ss -tlnp | grep ':8000'                   # 127.0.0.1:8000 only
sudo docker stats --no-stream                  # MEM LIMIT must read 256MiB for both
```

Import nothing: do not run `import-fixture` here. With `live_scanning = false` the worker schedules nothing; it only does hourly retention and a daily backup.

## 5. Publish on the tailnet

```sh
sudo tailscale serve --bg --https=8443 http://127.0.0.1:8000
tailscale serve status    # the existing :443 entry must still be there
```

Open `https://dragon.lonk-dorian.ts.net:8443` from another tailnet device and sign in. This works because `tailscale serve` connects from 127.0.0.1, keeps the browser's `Host`, and sets `X-Forwarded-Proto: https` (and `X-Forwarded-For` to the tailnet client) (see `addProxyForwardedHeaders` in tailscale's `ipn/ipnlocal/serve.go`). With `trusted_proxy_ips = ["127.0.0.1"]`, uvicorn takes the scheme as https, so the same-origin check accepts `Origin: https://dragon.lonk-dorian.ts.net:8443`. If sign-in returns "Cross-origin mutation rejected", the proxy headers are not arriving; check `tailscale serve status` and the config.

This step comes before enabling live scanning because adding the live network needs the web UI.

## 6. Enable live scanning for 192.168.30.0/24 on eth0

1. Edit `/etc/network-dragon/config.toml`: set `live_scanning = true`. Leave `notifications = false`. `allowed_cidrs` and `allowed_interfaces` are already set.
2. `cd /opt/network-dragon && sudo docker compose up -d --force-recreate`. Not `restart`: the config is bind-mounted as a single file, and `sed -i` or most editors replace the file, so a restarted container keeps reading the old copy. Recreate the containers after every config change, and check with `sudo docker compose exec web grep live_scanning /run/config.toml`.
3. In **Settings**, add a network: name `AI-Zone`, CIDR `192.168.30.0/24`, interface `eth0`, mode **live**.
4. Within about two minutes **Scans** should show a `discovery` job for `192.168.30.0/24` as succeeded, and **Devices** should list hosts with MAC addresses. Dragon's own address (192.168.30.123) is reported without a MAC, because Nmap does not ARP itself.
5. If the job fails, its diagnostics say why: interface down, route not on-link, or `Nmap failed`. Check `sudo docker compose logs worker` and repeat the capability check in step 2.

Addresses in `excluded_addresses` are passed to Nmap as `--exclude`, are never port-scanned, and are dropped from any evidence. On dragon that is the UniFi honeypot, 192.168.30.3, which answers ARP with the gateway's MAC and alerts on probes. One MAC answering for several addresses is treated as a conflict (it could be a spoofed MAC), unless that MAC is listed in `multihomed_macs`; a listed MAC is recorded as one device with several active addresses, and each address it gains is logged as an `identity.address_added` event. One address answered by several MACs is always a conflict.

Scanning stays in baseline review at first. Review devices and watch the ones that matter. Turn on `notifications` only after putting the Pushover credentials in the two secret files, restarting, and sending an explicit **Send test notification**.

## 7. Backups and upgrades

The worker writes a daily backup (SQLite online backup, checked for integrity, plus a JSON manifest; seven generations kept) to `/data/backups` inside the volume. Take one on demand and copy the backups off the Pi:

```sh
cd /opt/network-dragon
sudo docker compose exec web network-dragon backup
sudo rsync -a /var/lib/docker/volumes/network-dragon_dragon-data/_data/backups/ /srv/network-dragon-backups/
```

Backups contain the inventory and the administrator's password hash, so protect the copies. Back up `/etc/network-dragon` separately. Restore is covered in [operations](operations.md#backup-and-restore).

Upgrade to a newer `sha-` tag:

```sh
cd /opt/network-dragon
sudo docker compose exec web network-dragon backup
sudo sed -i 's/sha-.*/sha-YYYYYYY/' .env && sudo docker compose pull
sudo docker compose stop worker web
sudo docker compose run --rm --no-deps web init
sudo docker compose up -d web && curl -fsS http://127.0.0.1:8000/health/ready
sudo docker compose up -d worker
```

Then confirm that a fresh discovery succeeds. Repeat the capability check from step 2 for each new image. If a migration has to be rolled back, restore the pre-upgrade backup; launching the old image alone is not enough.

## Still to check by hand

Test firewall acceptance from the real network: HTTPS management access only over the tailnet, no new connections initiated from VLAN 30 into protected networks, and outbound access limited to Pushover HTTPS, DNS, time and updates. Include the IPv6 policy even though scanning is IPv4-only. Before turning on delivery, check presence against a real controlled outage, DHCP changes and service churn on VLAN 30. SMB/NFS live databases are unsupported; keep the volume on the Pi's SSD.
