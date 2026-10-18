# Acceptance record

All automated verification uses generated Nmap XML, synthetic documentation addresses, fake clocks, and fake/mock Pushover transports. Browser tests use a separate fixture database with live execution and delivery disabled. CI additionally runs the real image and Compose file with real Nmap against containers on a Linux bridge (see `docs/deployment.md`). Live scanning runs on dragon; Pushover delivery has not been validated yet.

The backend suite covers baseline/idempotency, post-baseline discovery, DHCP/reused IP identity, provisional identities, both absence thresholds, failed/partial/gapped discovery, mass disappearance, late evidence, independent port presence, exact closed/filtered transitions, uncertain aggregates, uncovered/timed-out ports, missing version evidence, quiet notification policy, accepted outage/recovery pairing, stale-message cancellation, mute, provider rejection/redaction, authentication/CSRF/session invalidation/rate limiting, merges, scope removal, backups, retention, lease fencing, queue coalescing, priority, and validation.

Playwright checks authenticated inventory, port detail, annotations, notifications policy, disabled live scanning, settings, mobile overflow, dark/light screenshots, logout, and rendering malicious-looking labels as text. Screenshots are written to `artifacts/` and are not committed. The initial desktop and mobile views were visually inspected.

Validated on dragon (Raspberry Pi 4, arm64, Docker Compose, live on VLAN 30 since October 18, 2026):

- The container deployment from `docs/deployment.md`: read-only root filesystems, UID/GID 10001, migrations through `init`, web and worker services.
- ARP discovery on arm64 as UID 10001 with only `NET_RAW`, on the real `eth0` through the physical switch, which CI's QEMU job cannot prove.
- Sign-in through `tailscale serve` on `https://dragon.lonk-dorian.ts.net:8443` (the same-origin check with the proxy's headers).
- The MCP endpoint over the tailnet with a bearer API token.

Not enforced on dragon: Compose's `mem_limit` values. The Pi kernel runs with `cgroup_disable=memory`, so Docker accepts the limits and ignores them. Memory use alongside Bluehood has not been measured.

Still required before production acceptance:

- Route/interface failures, process cancellation, worker restart mid-scan, and large/full-port output behavior on dragon.
- Multi-process lease behavior and backup during an actual long-running scan on the deployment filesystem.
- Actual Pushover credentials, HTTPS failures/rate limits, and an explicitly requested real test message.
- Firewall and IPv6 policy on the management path.
- The multi-day muted VLAN pilot: cadence/retention measurements and a review of notification eligibility before activation.

`PROGRESS.md` records the latest local check counts and the next steps.
