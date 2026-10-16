# Acceptance record

All automated verification uses generated Nmap XML, synthetic documentation addresses, fake clocks, and fake/mock Pushover transports. Browser tests use a separate fixture database with live execution and delivery disabled. No live network scan or real notification was performed.

The backend suite covers baseline/idempotency, post-baseline discovery, DHCP/reused IP identity, provisional identities, both absence thresholds, failed/partial/gapped discovery, mass disappearance, late evidence, independent port presence, exact closed/filtered transitions, uncertain aggregates, uncovered/timed-out ports, missing version evidence, quiet notification policy, accepted outage/recovery pairing, stale-message cancellation, mute, provider rejection/redaction, authentication/CSRF/session invalidation/rate limiting, merges, scope removal, backups, retention, lease fencing, queue coalescing, priority, and validation.

Playwright checks authenticated inventory, port detail, annotations, notifications policy, disabled live scanning, settings, mobile overflow, dark/light screenshots, logout, and rendering malicious-looking labels as text. Screenshots are written to `artifacts/` and are not committed. The initial desktop and mobile views were visually inspected.

Still required before production acceptance:

- Build and run the image on Linux; confirm wheel migrations, read-only filesystems, UID/GID, tmpfs/log bounds, shutdown, and restart.
- Demonstrate real Nmap against an explicitly configured lab, including ARP/MAC evidence, route/interface failures, process cancellation, permission minimums, and large/full-port output behavior.
- Validate multi-process lease behavior and backup during an actual long-running scan on the deployment filesystem.
- Exercise actual Pushover credentials, HTTPS failures/rate limits, and an explicitly requested real test message.
- Verify the VM/reverse-proxy/firewall management path and IPv6 policy.
- Run the multi-day muted VLAN pilot, measure cadence/retention, and review notification eligibility before activation.

These deployment inputs are deliberately unresolved rather than invented. `PROGRESS.md` records the latest local check counts and the next implementation steps.
