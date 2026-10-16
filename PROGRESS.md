# Network Dragon — progress / handoff

Updated October 16, 2026. Independent implementation; no NetAlertX code/assets. **No live network scans or real notifications have been performed.**

## Completed

- Phase 0: initialized Git workspace, backend/frontend layout, resolved Python/JS locks, lint/type/build checks, fixture-only CI definition.
- Phase 1: frozen Alembic schema; SQLite WAL/FKs/short transactions; safe XML normalization; typed profiles/target validation; shared CLI/worker ingestion; idempotent fixtures; authenticated inventory UI.
- Phase 2: MAC-scoped/provisional identity, address history, explicit aliases/audits, baseline review, watch/mute/acknowledge/archive controls, presence thresholds, freshness, gap resets, scope removal, health gating, mass-disappearance guard, conflict diagnostics.
- Phase 3: independent TCP observations, compact aggregate evidence, coverage-aware current ports, closed/filtered distinctions, service enrichment comparisons, searchable/filterable activity, device port/history views. Port/service events are excluded from the outbox and rechecked at dispatch.
- Phase 4: transactional outbox; fake and HTTPS Pushover transports; retries, cooldown, mute, stale-outage cancellation, accepted-outage recovery pairing, delivery history, separate explicit test request. Fixture evidence is forbidden from real delivery.
- Phase 5: responsive dark/light React screens, accessible labels/focus, authentication/CSRF/login limits/password changes, pagination, settings/status, identity alias controls, scans/diagnostics/cancellation. Pages/components separated for maintainability.
- Phase 6 groundwork: backup/restore with checksums and delivery paused on restore; bounded retention; migration/upgrade docs; shared-image web/worker Compose candidate with safe disabled defaults.

## Verified locally

- **88 pytest tests pass** (domain, API/auth, queue/fencing, provider mocks, identity conflicts, fake Nmap process, backup/restore including invalid manifests, retention, reused-IP port bindings, service evidence freshness, searchable history, and bounded device-list queries). Windows API tests require loopback access because asyncio uses a local socket pair; sandboxed calls otherwise hang.
- Ruff check and format pass; mypy passes for 26 backend source files.
- TypeScript/Vite production build and Prettier check pass; dependency locks resolve.
- **3 Playwright workflows pass**: authenticated fixture browsing/editing, evidence search, quiet history, disabled live execution, responsive layouts, themes, logout, hostile-label text rendering, and pagination using the API's returned page size. Initial desktop and dark/light mobile screenshots were visually reviewed in `artifacts/`. `scripts/check_browser.py` owns isolated setup/server teardown.
- Wheel built offline from cached dependencies; verified application/migration contents, installed into an isolated target, and successfully applied migrations using the installed wheel.
- GitHub CI is defined but has not run remotely. Docker is unavailable here; no Linux/container/Nmap-privilege validation is claimed.

## Decisions / limits

- Review follow-up: device-list enrichment uses four queries independent of page size (two for empty pages), including batched network health and open-port counts. Settings lookups are reused. Pagers use response limits. Restore reports missing/unreadable or malformed manifests, invalid checksums, and unreadable source databases before creating a destination.

- Keep installation settings in validated TOML; UI edits domain controls and reports runtime settings. Server-side opaque sessions need no signing secret.
- Keep normalized observations/evidence, not long-lived raw XML. Original fixtures remain in `tests/fixtures/nmap`.
- Scanner health is UI/history-only; optional health notifications and sentinels are not implemented. The guard acknowledgement records review without overriding uncertain evidence.
- Aliases preserve original observations and disable the source identity's independent monitoring; they do not combine multiple active NICs into one presence signal.
- Production packaging is a candidate with no raw-network capabilities granted. Resolve image/package digests and validate minimum Nmap-specific permissions on the actual Linux VM before enabling the worker.
- Browser timestamps currently use browser-local timezone; installation timezone is metadata. Very large backups need lease-duration/operational scheduling validation. Audit/identity growth needs pilot measurement.

## Next session

1. Read this file, `README.md`, and `docs/acceptance.md`; run the local fixture checks before changing behavior.
2. Obtain authorized CIDR/interface, Linux VM details, and management hostname/TLS/proxy source IPs. Keep `live_scanning=false` until configuration and lab authorization are explicit.
3. Build/run on Linux; validate non-root Nmap privileges, route/interface/cancellation/output bounds, read-only volumes, worker restarts and competing processes, backup during scanning, and firewall reachability. Fill acceptance evidence rather than assuming success.
4. Run a multi-day muted VLAN pilot and measure identification/cadence/storage. Configure Pushover secrets outside Git, explicitly request a real test, and review baseline/watch policies before activation.

Run instructions and fixture import commands: `README.md`. No real deployment values or credentials were invented. The local default database is initialized but has no default administrator; create one interactively. Browser-test credentials and databases live only in ignored `.tmp/` artifacts.
