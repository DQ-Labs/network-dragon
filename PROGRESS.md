# Network Dragon — progress / handoff

Updated October 18, 2026. Independent implementation; no NetAlertX code/assets. **Live since October 18 on dragon** (Raspberry Pi 4, arm64, Compose), scanning VLAN 30, 192.168.30.0/24 on `eth0`, with the honeypot 192.168.30.3 in `excluded_addresses`. **Pushover delivery has not been validated yet.**

## Completed

- Phase 0: initialized Git workspace, backend/frontend layout, resolved Python/JS locks, lint/type/build checks, fixture-only CI definition.
- Phase 1: frozen Alembic schema; SQLite WAL/FKs/short transactions; safe XML normalization; typed profiles/target validation; shared CLI/worker ingestion; idempotent fixtures; authenticated inventory UI.
- Phase 2: MAC-scoped/provisional identity, address history, explicit aliases/audits, baseline review, watch/mute/acknowledge/archive controls, presence thresholds, freshness, gap resets, scope removal, health gating, mass-disappearance guard, conflict diagnostics.
- Phase 3: independent TCP observations, compact aggregate evidence, coverage-aware current ports, closed/filtered distinctions, service enrichment comparisons, searchable/filterable activity, device port/history views. Port/service events are excluded from the outbox and rechecked at dispatch.
- Phase 4: transactional outbox; fake and HTTPS Pushover transports; retries, cooldown, mute, stale-outage cancellation, accepted-outage recovery pairing, delivery history, separate explicit test request. Fixture evidence is forbidden from real delivery.
- Phase 5: responsive dark/light React screens, accessible labels/focus, authentication/CSRF/login limits/password changes, pagination, settings/status, identity alias controls, scans/diagnostics/cancellation. Pages/components separated for maintainability.
- Phase 6 groundwork: backup/restore with checksums and delivery paused on restore; bounded retention; migration/upgrade docs; shared-image web/worker Compose candidate with safe disabled defaults.
- Deployment (PR #3): arm64/amd64 image published from `main` to GHCR, Compose for dragon, CI jobs `verify`, `container` and `arm64` on every PR (`publish` on `main` only). The project moved from GitLab to GitHub; `.gitlab-ci.yml` is gone.
- Dashboard rework (PR #4); `excluded_addresses` and `multihomed_macs` (PR #5).
- Follow-ups (Oct 18): MAC vendor from Nmap's OUI lookup stored on devices (migration `0003`), shown and searchable, and in MCP output; a deliberately cancelled discovery no longer marks the network unhealthy; provider exceptions become a sanitized `provider_error` outcome so test notifications and outbox entries never stay `sending`; backup/restore close their SQLite connections and delete a copy that fails its integrity check; a missing `*_FILE` secret reads as unconfigured instead of a 500; `/api/v1/devices` filters on `acknowledged`/`watched`/`archived` (archived excluded by default) and `/api/v1/events` on `baseline`, and Activity hides baseline observations unless asked.
- Agent access (Oct 18): read-only API tokens (migration `0002`, SHA-256 digests only, `create-token`/`list-tokens`/`revoke-token`, audited, `last_used_at` stamped at most once a minute); a stateless streamable-HTTP MCP endpoint at `/mcp` (official `mcp` SDK) with five compact read-only tools; authenticated OpenAPI at `/api/v1/openapi.json`. Device/event/status/scan queries now live in `api/queries.py`, shared by the API and MCP. Review fixes: notification history uses two batched lookups instead of two per row, and device/event search escapes LIKE wildcards.

## Verified locally

- **122 pytest tests pass** (domain, API/auth, queue/fencing, provider mocks, identity conflicts, fake Nmap process, backup/restore including invalid manifests, retention, reused-IP port bindings, service evidence freshness, searchable history, and bounded device-list queries, token scope/revocation/expiry, unchanged cookie+CSRF flow, every MCP tool through the real `/mcp` endpoint plus the official MCP client over a live uvicorn socket, authenticated OpenAPI, LIKE-wildcard escaping, batched notification lookups, vendor parsing and the 0002→0003 upgrade, cancel vs. failure health, provider exceptions, closed backup connections, missing secret files, device/event filters). Windows API tests require loopback access because asyncio uses a local socket pair; sandboxed calls otherwise hang.
- Ruff check and format pass; mypy passes for 28 backend source files.
- TypeScript/Vite production build and Prettier check pass; dependency locks resolve.
- **9 Playwright specs pass**: authenticated fixture browsing/editing, evidence search, quiet history with the baseline toggle, vendor search, disabled live execution, responsive layouts, themes, logout, hostile-label text rendering, pagination using the API's returned page size, acknowledge/watch/mute/archive flows, and a screenshot tour of every page (desktop and phone, dark and light). `scripts/check_browser.py` owns isolated setup/server teardown.
- GitHub Actions runs all of the above (`verify`), plus the real image and `deploy/compose.yaml` natively on amd64 (`container`, including ARP as UID 10001) and on arm64 under QEMU (`arm64`, which cannot prove ARP).

## Validated on dragon

- The container deployment runs as documented in `docs/deployment.md`.
- ARP discovery on arm64 works as UID 10001 with only `NET_RAW` (so the pulled image kept nmap's `cap_net_raw+ep`).
- Sign-in through `tailscale serve` at `https://dragon.lonk-dorian.ts.net:8443` works.
- The MCP endpoint was checked over the tailnet with an API token.
- **Memory limits are not enforced on dragon**: the Pi kernel runs with `cgroup_disable=memory`, so Compose's `mem_limit: 256m` is accepted but ignored. Memory use alongside Bluehood is unmeasured.

## Decisions / limits

- Review follow-up (Oct 17): retention now drains its backlog in short 500-row transactions within a 10-second worker budget (CLI `retention` runs unbounded), and a port that an earlier unambiguous aggregate proved closed/filtered is recorded as a `port.state` change when it opens instead of `port.baseline`.
- Review follow-up: device-list enrichment uses four queries independent of page size (two for empty pages), including batched network health and open-port counts. Settings lookups are reused. Pagers use response limits. Restore reports missing/unreadable or malformed manifests, invalid checksums, and unreadable source databases before creating a destination.

- Keep installation settings in validated TOML; UI edits domain controls and reports runtime settings. Server-side opaque sessions need no signing secret.
- Keep normalized observations/evidence, not long-lived raw XML. Original fixtures remain in `tests/fixtures/nmap`.
- Scanner health is UI/history-only; optional health notifications and sentinels are not implemented. The guard acknowledgement records review without overriding uncertain evidence.
- Aliases preserve original observations and disable the source identity's independent monitoring; they do not combine multiple active NICs into one presence signal.
- The worker container holds only `NET_RAW`, and only nmap can use it (file capability); see `docs/deployment.md`.
- Browser timestamps currently use browser-local timezone; installation timezone is metadata. Very large backups need lease-duration/operational scheduling validation. Audit/identity growth needs pilot measurement.

## Next session

1. Read this file, `README.md`, and `docs/acceptance.md`; run the local fixture checks before changing behavior.
2. Upgrade dragon to the image from this PR's merge commit (migration `0003` runs at `init`; take a backup first, as in `docs/deployment.md` step 7).
3. Decide on memory limits: accept them as unenforced, or try enabling the memory cgroup on the Pi and recheck `docker info`.
4. Continue the muted VLAN 30 pilot: measure cadence, storage and identity stability, and check presence against a controlled outage and DHCP changes.
5. Firewall and IPv6 policy checks; then Pushover secrets, an explicit real test, and a review of baseline/watch policy before finishing baseline review.

Run instructions and fixture import commands: `README.md`; the dragon runbook: `docs/deployment.md`. No credentials are stored in Git. The local default database is initialized but has no default administrator; create one interactively. Browser-test credentials and databases live only in ignored `.tmp/` artifacts.
