# Network Dragon — implementation plan

Prepared: October 16, 2026

Status: Ready for implementation in a new workspace. This document is a plan, not a record of implemented or tested behavior.

Intended project directory: `C:\dev\network-dragon`

## 1. Purpose and confirmed requirements

Build a focused, self-hosted network inventory and monitoring application around Nmap, SQLite, and Pushover, with a polished web interface.

The user wants to monitor both device presence and changes to exposed services. Nodes in the AI-Zone VLAN frequently start and stop services, so port changes are useful history, not actionable notifications.

Confirmed requirements:

- Discover devices and track whether they are present, absent, or currently unobservable.
- Persist device inventory, scan results, and change history in a database.
- Send Pushover notifications for relevant device-presence events.
- Record port and service changes in the database and show them in the interface.
- **Never send Pushover notifications because a port or service changed.** This also excludes port-change digests, service-version alerts, and generic “any event” notification rules.
- Provide a visually polished interface for reviewing devices, history, scans, and settings.
- Build a new application, independent of NetAlertX. Do not fork it or copy its source/assets into this project.
- Deliver a maintainable deployment suitable for the user's Proxmox environment.

Everything below that is not stated above is a proposed implementation decision or default. Keep those defaults easy to change without expanding the product into a general monitoring platform.

## 2. Scope and assumptions

### Initial operating environment

- One administrator, one scanner, one installation, and initially one IPv4 VLAN.
- A small network: design and test initially for up to 256 configured addresses and approximately 100 active devices. These are capacity targets, not measured performance claims.
- Linux is the production runtime. Windows is a supported development environment using saved Nmap fixtures; a Linux VM is needed to validate real scanning and packaging.
- The scanner has an interface on the monitored VLAN. Management access can reach the web interface through explicit firewall rules or a reverse proxy.
- Internet access is needed for installation/updates and Pushover delivery, not for local inventory collection.
- Confirm the actual CIDR, interface, management-access path, and deployment resources during implementation/deployment. Never assume addresses from the previous NetAlertX repository.

### Included in version 1

Device discovery; scheduled/manual TCP scans; inventory and annotations; presence state transitions; historical port/service observations; Pushover presence notifications; authentication; scan diagnostics; retention; consistent backups; and a reproducible deployment.

### Excluded from version 1

Plugin systems, GraphQL, MCP, raw-SQL endpoints, arbitrary shell commands, custom NSE scripts, vulnerability scanning, OS fingerprinting, packet capture, SNMP, router/cloud integrations, remote scanner fleets, multi-tenant access, complex RBAC, and additional notification providers.

Automatic IPv6 discovery and UDP scanning are deferred. Preserve address-family and transport fields in the schema, but label the first release accurately as IPv4/TCP monitoring. Do not attempt exhaustive IPv6 subnet enumeration.

## 3. Product behavior

### Presence and port monitoring are independent

Use separate discovery and port-scan jobs, intervals, results, and event types. Presence must not be inferred from whether a particular application port is open. Closing all monitored ports must not by itself make a device offline.

Default discovery cadence: every 2 minutes. Default port-scan cadence: every 15 minutes for recently observed devices. Both are configurable within bounded limits.

Polling records observed states. A service that starts and stops between scans can be missed; show scan intervals and last-observed timestamps clearly. Do not imply continuous monitoring.

### Device identity

- Give every device an internal UUID independent of its IP address.
- For the initial local VLAN, prefer a normalized MAC address scoped to the monitored network as identity evidence.
- Track address bindings with first/last-observed times. A DHCP address change should normally update the existing device.
- If an IP appears with a different MAC, close the previous binding and treat it as different identity evidence. Never silently merge devices solely because they shared an IP.
- If no MAC is available, use a provisional network/address identity and visibly mark its lower confidence.
- Hostnames are labels, not unique identifiers. A hostname change must not create a new device.
- MAC randomization, multiple NICs, duplicate addresses, and missing MAC data cannot be resolved perfectly by Nmap. Allow administrator-reviewed aliasing/merging with audit history; never guess silently.
- Preserve observations on their original identity and resolve merged devices through a canonical-device mapping, so a merge does not destroy evidence.

### Presence state machine

Keep device presence separate from inventory acknowledgement and scanner health.

Presence states:

| State | Meaning |
|---|---|
| Unknown | Insufficient trustworthy discovery evidence exists. |
| Online | The device was observed in a qualifying discovery scan. |
| Suspected missing | It was absent from a qualifying scan, but the absence threshold is not met. |
| Offline | It has met the configured absence threshold. |

Track observation freshness separately. During a scanner outage, show “last known online/offline; data stale” rather than rewriting every device to unknown or offline.

Proposed transition rules:

1. A positive discovery observation moves unknown/offline/suspected-missing to online and resets missed-scan counters.
2. Count an absence only when the discovery scan successfully covered that device's expected network/address, used an appropriate discovery method, and passed scanner-health checks.
3. Default offline threshold: at least three consecutive qualifying misses and at least five minutes since the last positive observation. Require both conditions. Actual detection latency depends on the schedule.
4. Failed, cancelled, truncated, expired, or out-of-scope scans neither increment misses nor produce offline events. A gap invalidates the consecutive-miss sequence; restart it after trustworthy scanning resumes.
5. A returning device creates one recovery transition per offline episode. Recovery from suspected-missing is recorded without generating an outage/recovery alert pair.
6. A device removed from scan scope becomes “not monitored,” not offline.
7. Port scans do not drive this state machine in version 1. Keep its evidence source predictable.

Scanner health must include interface existence/up-state, expected addressing/routing, process success, complete parseable output, and coverage. An exit code alone does not prove that the network was observable.

Add a conservative mass-disappearance guard: if at least three devices were online and 80% or more disappear together, flag the discovery run as suspect and withhold negative presence transitions. Positive observations may still update last-seen information. Provide an explanation and a way to inspect/acknowledge the condition. Where configured, a stable in-scope sentinel can help confirm network visibility. Do not automatically classify every device offline merely because repeated empty scans succeed. Document the tradeoff: a real whole-network outage may initially be shown as an observability problem.

### Baseline and new devices

- Setup starts in baseline mode. The first valid discovery establishes existing devices without sending new-device alerts.
- Show the resulting inventory and let the administrator activate notifications after reviewing it. Scanning can continue during review.
- New identities discovered after activation produce a new-device event and, if enabled, a notification.
- Marking a device known/acknowledged affects its review badge, not whether the system remembers that it was already discovered.
- Restarting the app, upgrading it, or changing a label must not resend new-device alerts.
- Adding a new monitored network starts a baseline for that scope; it does not reset existing networks.

### Port and service history

Store protocol, port number, Nmap state/reason, service name, detection method/confidence, and optional product/version information, with scan and observation timestamps.

Record observed transitions such as:

- First observation of an open port.
- Explicit open-to-closed and closed-to-open transitions.
- Open-to-filtered or other visibility transitions, labeled accurately rather than called “closed.”
- Changes in probed service/product/version information.

Rules preventing misleading history:

- A port not included in the scan is “not scanned,” not closed.
- A host timeout or partial result does not close previously open ports.
- A device going offline does not create a synthetic closure event for every port.
- Compare observations for the same device, protocol, and port only when the new scan supplies evidence for that port.
- Record scan coverage and profile revision. Changing profiles starts a baseline for newly covered ports; dropping ports from coverage is not a service change.
- Interpret Nmap aggregate `extraports` output only when the state of omitted ports can be determined unambiguously from coverage and counts. Otherwise preserve uncertainty.
- Separate port-number-based service guesses from actively probed service identities. The guess “http” is not proof that HTTP was detected.
- Avoid generating repeated service-change events when one scan simply lacks optional version information. Normalize equivalent results; distinguish missing evidence from changed evidence.
- Preserve last-known port information with stale timestamps when a device is offline.
- Baseline observations should be browsable but distinguished from subsequent changes.

**Port and service events are ineligible for Pushover delivery at the domain-policy layer, not merely hidden by a UI checkbox.**

## 4. Notifications

### Proposed defaults

| Event | Persist/show in UI | Pushover default |
|---|---|---|
| New device after baseline | Yes | Enabled globally after notification activation |
| Watched device offline | Yes | Enabled for explicitly watched devices |
| Watched device recovered | Yes | Enabled when its offline episode was notified |
| Unwatched device offline/recovered | Yes | Disabled |
| IP/hostname changed | Yes | Disabled |
| Port opened/closed/filtered | Yes | Never |
| Service/product/version changed | Yes | Never |
| Scanner unhealthy/recovered | Yes | Optional separate setting, disabled initially |

“Watched” is an administrator-selected device property. This prevents laptops and transient nodes from generating unwanted absence alerts. The user can watch all fixed nodes if desired.

### Delivery semantics

- Persist a domain event and its eligible notification-outbox record in the same database transaction.
- Give each event/recipient delivery a unique deduplication key. Reprocessing a scan must not enqueue it twice.
- The dispatcher sends only explicitly allowlisted presence event types, plus the separately enabled scanner-health category. Unknown event types fail closed for notification eligibility.
- Use HTTPS with certificate verification. Keep the application token and user key server-side.
- Bound connection/read timeouts and retry transient failures using exponential backoff with jitter. Honor provider guidance and quota responses; surface rejected credentials without retry storms.
- Store attempt count, next attempt, status, and sanitized provider response/error.
- Do not claim exactly-once delivery: an ambiguous network failure after provider acceptance can produce a duplicate on retry. Document this external-delivery limitation.
- A recovery notification should be sent only for an offline episode whose notification was accepted, unless the user explicitly changes that policy later.
- If the device recovers before its offline notification has been sent, cancel the unsent stale outage and record the brief episode in history. Recheck state before retrying old messages.
- Default to ordinary Pushover priority; do not use emergency repeating notifications.
- Apply a short per-device cooldown for repeated flapping and expose suppression reasons. Do not send every missed discovery as a new alert.
- A temporary “mute until” control suppresses presence delivery without stopping scans/history. Events suppressed while muted are not replayed on unmute.
- Provide “send test notification” and a delivery history screen. Testing is an explicit user action, not an automatic startup message.

Keep device notifications focused on identity, presence, and observation time. Do not attach noisy port-change summaries to them.

## 5. Architecture and technology choices

Recommended stack:

- Backend: Python, FastAPI, Pydantic request/response models.
- Persistence: SQLite, SQLAlchemy, Alembic migrations.
- Frontend: React, TypeScript, Vite, Tailwind CSS, and a small consistent icon set such as Lucide. Use TanStack Query for server-state fetching/cache invalidation; avoid a separate global state framework unless a concrete need emerges.
- Scanning: installed Nmap executable, subprocess argument arrays, XML output.
- Tests: pytest for backend/domain/integration tests and Playwright for critical browser flows.
- Packaging: one application repository and one versioned application image with separate web and worker entrypoints.

Resolve supported language/framework versions when implementation begins and commit dependency lockfiles. Do not install unbounded “latest” dependencies on production startup.

```text
Browser -- HTTPS --> reverse proxy --> web process
                                       |
                                   SQLite database
                                       |
                                  worker process
                                  /            \
                       Nmap subprocess      Pushover HTTPS
                             |
                        AI-Zone VLAN
```

### Process responsibilities

Web process:

- Authentication, validation, inventory/history queries, settings, and queued scan requests.
- Serve built frontend assets and versioned API routes from one origin.
- Never launch Nmap directly and never wait synchronously for a scan to finish.
- Expose no SQL execution endpoint and no browser-visible shared admin API token.

Worker process:

- Schedule recurring jobs and claim manual jobs.
- Validate targets/profiles again at execution time.
- Run Nmap with deadlines/output limits, normalize results, update domain state, and write events/outbox records.
- Dispatch notifications and perform scheduled retention/backup jobs.
- Maintain a heartbeat and current-job status.

Do not run a scheduler inside every web worker. Version 1 has one worker instance, protected by a database lease. Use a bounded scan executor so the worker can renew its lease, update heartbeat, and deliver notifications while Nmap runs.

A SQLite-backed job queue is sufficient here. Do not add Redis, Celery, Kafka, or a separate database server for version 1.

### Job execution and crash recovery

- Jobs transition through queued, running, succeeded, partial, failed, cancelled, or expired.
- Claim jobs transactionally with a lease owner, generation/fencing value, expiry, and attempt count.
- Never hold a database write transaction while Nmap or an HTTP request runs.
- Use a unique job key for each scheduled time window to prevent duplicate schedule insertion.
- Default to one scan subprocess at a time. Prioritize discovery over routine port scans; break port workloads into bounded per-device jobs so discovery is not starved.
- Coalesce redundant manual requests and skip superseded scheduled windows instead of replaying a backlog after downtime.
- Store cancellation requests; terminate the Nmap process group gracefully, then force termination after a bounded grace period.
- An expired job becomes abandoned/failed, not a valid empty result. Reject results from a worker with an obsolete fencing value.
- Deduplicate result application by scan ID and compare observation times so late results cannot overwrite newer device state.
- On restart, reconcile jobs/leases and resume future schedules. Do not repeat completed events or notifications.

## 6. Scanning implementation

### Discovery

Use a fixed Nmap discovery profile based on `-sn`, with numeric targets, explicit interface selection where appropriate, and XML output. For an on-link IPv4 network, validate ARP discovery and MAC collection in the intended Linux deployment.

Nmap behavior differs depending on privileges and network topology. A degraded unprivileged TCP-probe mode must be explicitly labeled; do not silently present it as equivalent to local ARP discovery.

Keep reverse DNS resolution out of the critical discovery path. Add optional bounded hostname enrichment separately so DNS problems do not turn a scan into a presence failure.

### Port scanning

- Default to a bounded TCP connect profile (`-sT`) and the commonly used top 1,000 TCP ports.
- Let the administrator replace that scope with a validated explicit port set. Ephemeral development services may use ports outside the default; make the coverage visible.
- Provide a manual full-TCP profile with a longer, explicit runtime budget, rather than running all 65,535 ports every few minutes.
- Store the actual expanded port coverage from Nmap scan metadata, not only the label “top 1,000.”
- For hosts recently confirmed by discovery, `-Pn` can avoid a redundant discovery gate, but it must never count as proof that a host is online.
- Make active service/version detection a separate optional, slower enrichment profile; do not use `-A`, default NSE scripts, or OS detection as part of routine scans.
- Initially suggest 60 seconds per routine device port job, with bounded concurrency and configurable limits. Tune against measured results on the real VLAN rather than assuming this is sufficient for all hosts.

### Target and execution controls

- Parse IPs/CIDRs using an IP-address library. Accept numeric in-scope targets, not shell fragments or hostnames that can resolve outside scope.
- Enforce an installation-level CIDR allowlist and maximum target count. The UI may schedule only within it.
- Validate port numbers/ranges and interface names against known values. Reject flags in target fields.
- Build argument arrays with `shell=False`; never concatenate a command string.
- Do not expose arbitrary Nmap arguments, output paths, scripts, or file-loading options through the API.
- Record the executable version, profile revision, sanitized arguments, timing, and result status.
- Bound process duration and XML/stderr size. Use private temporary paths and clean up only files created by the job.
- Parse XML with external entity resolution and network/file fetching disabled. Accept Nmap's normal document structure without resolving its external resources.
- Treat hostnames, service banners, and all scan output as untrusted text; escape them in the UI.
- Validate output completion and per-host coverage before applying negative state transitions. Preserve diagnostic partial results without treating them as a successful full scan.

## 7. Data model

Use migrations from the first implementation. Store timestamps in UTC and render in the selected user timezone, initially America/New_York.

| Entity | Main responsibility |
|---|---|
| networks | Scope ID, CIDR, interface, enabled state, baseline state, discovery/port schedules. |
| devices | UUID, network, display name, notes, acknowledged/watched/archived flags, presence, freshness, first/last seen, miss counters, mute-until, canonical identity link. |
| device_identifiers | MAC and provisional identity evidence with confidence/source; enforce appropriate uniqueness. |
| device_addresses | IPv4/IPv6 address bindings and validity/observation timestamps. |
| scan_profiles | Typed profile settings, immutable revisions, requested coverage and time budgets. |
| scan_jobs / scan_runs | Scheduling, leases, attempts, execution metadata, status, coverage, health classification, result checksum, diagnostics/artifact reference. |
| host_observations | Per-run device/address evidence, observed time, discovery outcome, coverage validity. |
| port_observations | Per-run observed port/protocol/state/service facts, including evidence type. |
| current_ports | Latest trustworthy state per device/protocol/port with source scan and freshness; a query projection, not the sole history. |
| events | Immutable typed presence, identity, port, service, and scanner-health events with before/after facts, baseline marker, scan ID and event version. |
| notification_outbox / delivery_attempts | Eligible delivery work, deduplication key, episode association, retry state, and sanitized provider outcomes. |
| settings | Validated nonsecret application settings with schema version. |
| users / sessions | One-admin authentication and server-side session lifecycle. |
| audit_log | Settings changes, watch/mute actions, identity merges, manual scans, and administrative operations. |

Use unique constraints for scan application, logical event generation, notification delivery keys, and current-port identity. Index device/network IDs, timestamps, event types, job states, and next-attempt times.

Use SQLite WAL mode, foreign keys, busy timeouts, short transactions, and one local filesystem volume shared by web/worker. Do not place the live database on SMB/NFS.

Port observations can grow quickly. Store explicit observations and compact coverage summaries rather than inserting 65,535 rows per device on every scan. Preserve enough evidence to explain events.

## 8. Web interface and API

### Visual direction

Build a calm, polished operations dashboard with a restrained Network Dragon identity. Use strong typography, consistent spacing, clear status badges, and a compact device table. A tasteful dragon mark can be added later; elaborate branding must not delay usable monitoring.

Support dark and light themes, keyboard navigation, visible focus, accessible contrast, and responsive layouts. Status must be conveyed by text/icons as well as color. Do not use animated noise, excessive gradients, or a wall of charts as a substitute for useful information.

### Screens

1. **Overview:** online/offline counts, devices awaiting acknowledgement, last successful discovery, scanner health/freshness, recent presence events, and a separate quiet recent-port-changes panel.
2. **Devices:** sortable/filterable inventory with name, IP, MAC, presence, last seen, watch state, and open-port count. Actions: acknowledge, rename, notes, watch, mute, rescan, archive.
3. **Device detail:** identity/address history, presence timeline, current ports with evidence/freshness, searchable port/service history, and scan failures relevant to the device.
4. **Activity:** filters for presence, identity, port/service, and system events. Port changes use neutral informational styling, not alarming red notification badges.
5. **Scans:** queued/current/recent jobs, profiles, covered targets/ports, duration, status, cancellation, and sanitized error details. Use indeterminate progress when exact progress is unavailable.
6. **Notifications:** delivery history, pending/suppressed/failed messages, presence policy, watch controls, and explicit test action. State prominently that port changes are history-only.
7. **Settings:** monitored scope, cadence, thresholds, timezone, retention, backup status, credentials configuration status, and password change.

Provide loading, empty, stale, failed, and partially successful states intentionally. Preserve filters in URLs and allow direct links to devices/events. Use server-side pagination for inventory and history.

### API outline

- `/api/v1/session`: login, logout, current session, password change.
- `/api/v1/overview`: aggregate dashboard data and freshness.
- `/api/v1/devices`: paginated list, details, annotations, watch/mute/archive controls.
- `/api/v1/devices/{id}/observations`, `/ports`, `/events`: paginated history and current state.
- `/api/v1/scans`: queue a validated scan, list runs, inspect a run, request cancellation.
- `/api/v1/events`: filtered activity feed.
- `/api/v1/notifications`: delivery history and explicit test action.
- `/api/v1/settings`, `/networks`, `/scan-profiles`: validated administration.
- Minimal `/health/live` and `/health/ready` endpoints with no inventory or credentials.

Use named request models; never pass arbitrary column/table names or SQL from clients. Mutations require an authenticated session and CSRF protection. Use modest polling initially (for example 5 seconds on a running scan screen and 15 seconds on the overview); add SSE only if there is a demonstrated benefit.

## 9. Authentication, secrets, and boundaries

- Require authentication from first useful access. There is no default password or public setup mode.
- Create the initial administrator using a local interactive CLI command with hidden password entry before exposing the service. Never print or commit credentials.
- Hash passwords with a maintained Argon2id implementation; use random server-side sessions and rotate the session identifier on login.
- Cookies are HttpOnly, SameSite, and Secure in HTTPS deployments. Protect all session-authenticated mutations against CSRF and apply login rate limits.
- Require current-password verification for password changes and invalidate other sessions afterward.
- Keep development HTTP exceptions explicit and local; do not silently weaken production cookie settings.
- Store Pushover credentials and the session secret in permission-restricted mounted secret files/environment configuration outside the repository and database exports. The first version's UI can report configured/not-configured and send tests without returning secrets.
- If credential editing in the UI is later added, design protected secret storage explicitly; do not invent encryption with a key stored next to the ciphertext.
- Never log passwords, cookies, tokens, full notification credentials, or secrets in diagnostic exports.
- Keep the web process unprivileged with no scanning capabilities. The worker exposes no listening HTTP service.
- Test and document the minimum privileges needed by Nmap for local discovery. Avoid privileged containers, host PID mounts, Docker socket mounts, blanket sudo, and raw-socket capabilities on the Python interpreter itself.
- A limited-capability scanner container still has access to the monitored network. Network allowlists and external firewall policy remain necessary even with application validation.
- No telemetry, cloud inventory sync, or automatic outside-network scans.

## 10. Deployment and operations

### Recommended first production target

A small dedicated Debian-based Linux VM on Proxmox, with one interface attached to AI-Zone. Start with approximately 2 vCPUs, 2 GB RAM, and 16–24 GB disk as provisional sizing; measure actual use and retention growth.

Package web and worker as separate Compose services from the same application image:

- Web uses normal bridge networking and exposes only its HTTP port to a trusted reverse proxy/management path.
- Worker uses Linux host networking to reach the VM's on-link network and does not publish any ports.
- Both use the same persistent local data volume with compatible UID/GID permissions.
- Web drops all unnecessary capabilities. Worker gets only tested capabilities required for its selected Nmap discovery method, with a non-root runtime where validated.
- If runtime privilege requirements are not yet validated, treat packaging as incomplete; do not solve it by enabling `privileged: true`.
- Use read-only application filesystems and bounded writable temporary storage, process limits, log rotation, and restart policies.
- Do not configure `net.*` sysctls in a Compose service using host networking. Do not alter Proxmox host networking merely to run this app.
- Pin releases and image digests for deployments. Provide a sample configuration containing placeholders only.

A native unprivileged LXC installation can be a later supported option after separate validation of permissions, networking, and restart behavior. Do not make Docker-in-LXC or a custom LXC installer the first release's prerequisite.

### Access and firewall policy

- Restrict the web interface to trusted management sources; terminate HTTPS at the existing reverse proxy or a documented small proxy service.
- Allow required management-session replies, while denying new AI-Zone-initiated connections to protected internal/management networks.
- Consider IPv6 firewall policy even though version 1 discovery is IPv4-only.
- Allow Pushover HTTPS, required DNS/time services, and explicitly planned update access. Local scans should continue when the internet is unavailable.
- Verify these rules from the actual deployment network. Application configuration cannot substitute for firewall testing.

### Retention and backup defaults

- Raw scan artifacts/diagnostics: 7 days, bounded by a configurable disk quota.
- Detailed host/port observations: 30 days.
- Presence/identity/port-change events: 365 days.
- Delivery attempts: 90 days.
- Device identities, annotations, and current state: retained until explicitly removed/archived according to policy.

Show retention settings and disk usage. Preserve the compact evidence needed by retained events even after raw observations/artifacts expire. Run cleanup in small batches and keep it out of active scan transactions.

Use SQLite's online backup API to produce a consistent database snapshot. Do not copy only a live WAL-mode `app.db`. A database snapshot, nonsecret configuration, and required managed artifacts should form a versioned backup set; credentials are backed up separately under the administrator's control.

Maintain several backup generations, record checksums/schema/application versions, and provide a documented restore rehearsal. On restoration, pause delivery until the administrator reconciles pending notifications so old outages are not replayed accidentally.

Upgrade procedure: create/verify backup, stop worker, apply controlled migration, start the new release, verify health, and resume scans. A destructive schema change may require restoring the pre-upgrade database rather than merely running the old image.

## 11. Suggested repository layout

```text
network-dragon/
  NETWORK_DRAGON_PLAN.md
  README.md
  pyproject.toml
  <Python dependency lockfile>
  backend/
    network_dragon/
      api/
      auth/
      domain/          # identity, presence, port comparison, notification policy
      persistence/     # models, repositories, transactions
      scanner/         # profiles, validation, subprocess, XML normalization
      worker/          # scheduling, claims, recovery, dispatcher
      notifications/   # Pushover client and delivery results
      operations/      # health, backup, retention
      cli.py
    migrations/
  frontend/
    src/
      components/
      pages/
      api/
      styles/
    package.json
    <JavaScript dependency lockfile>
  tests/
    unit/
    integration/
    fixtures/nmap/
    browser/
  deploy/
    Dockerfile
    compose.yaml
    config.example.toml
  docs/
    architecture.md
    deployment.md
    operations.md
    acceptance.md
```

Keep domain functions independent of FastAPI, subprocess execution, and HTTP delivery so the consequential rules can be tested with deterministic fixtures and a fake clock.

## 12. Implementation phases and exit criteria

### Phase 0 — decisions and skeleton

Confirm proposed defaults, initialize the new repository, record stack/runtime versions, create lockfiles, and document the one-admin/one-scanner model. Record unresolved deployment values as placeholders rather than inventing them.

Exit: backend/frontend development starts reliably; formatting/type checks and a minimal CI pipeline run; no live scan or external notification occurs automatically.

### Phase 1 — persistence and scanning vertical slice

Implement migrations, typed profiles, target validation, Nmap fixture parser, job/run storage, a scan worker, and an authenticated minimal inventory page. Add a CLI fixture-import mode and an explicitly invoked live-scan command.

Exit: a saved XML result travels through the real ingestion/database path to the UI; repeated import is idempotent; real Linux Nmap execution can be demonstrated against an explicitly configured lab scope.

### Phase 2 — presence and identity correctness

Implement baseline review, identity/address history, freshness, missed-scan thresholds, scope removal, scanner-health gating, and mass-disappearance handling. Add watch/mute/acknowledge controls.

Exit: deterministic tests prove the state machine and the UI clearly distinguishes offline, suspected-missing, stale, and unmonitored devices.

### Phase 3 — quiet port history

Implement current-port projections, coverage-aware comparisons, profile revisions, service enrichment, and device port/history screens.

Exit: open/closed/filtered transitions are recorded accurately; incomplete/uncovered data never creates false closure events; **all port/service scenarios produce zero notification-outbox entries**.

### Phase 4 — Pushover delivery

Implement typed notification policy, transactional outbox, retries, cooldown/muting, outage/recovery pairing, stale-message cancellation, and delivery history. Use a fake provider for development/tests.

Exit: presence notifications behave correctly through simulated provider failures and restarts. A real test message is sent only after credentials are supplied and the user explicitly triggers it.

### Phase 5 — finish the interface and administration

Complete overview/device/activity/scan/settings screens, authentication hardening, accessibility, responsive layouts, empty/error states, pagination, and visual consistency. Do not defer all UI work to this phase; earlier phases already deliver usable slices.

Exit: critical browser workflows pass and screenshots are visually reviewed at desktop and mobile sizes.

### Phase 6 — deployment, recovery, and pilot

Validate the Linux VM deployment, Nmap permissions, read-only filesystems, single-worker behavior, backup/restore, migrations, log/retention bounds, and firewall reachability. Run a multi-day pilot on the actual VLAN with notifications initially muted.

Exit: device identification and scan cadence are acceptable on real nodes; no unexplained offline storms; service churn remains quiet; backup restoration works; notification policies are reviewed before activation.

Do not promise a delivery date before the first Linux scanning/deployment validation. The initial dashboard will be easier than proving trustworthy presence and recovery behavior.

## 13. Required tests and acceptance scenarios

Tests should protect behavior rather than mirror implementation details.

### Discovery and identity

- Initial baseline with several devices generates no external messages.
- One new device after activation creates one event/notification; repeat scans and restarts do not duplicate it.
- Same MAC at a new IP retains the device identity.
- Reused IP with a different MAC does not overwrite the old device.
- Missing MAC, random MAC, duplicate IP, and identity merge behavior are explicit and auditable.
- Failed/partial/cancelled scans and gaps do not advance offline counters.
- Three qualifying misses plus minimum duration create one offline episode; return generates one recovery event.
- Changing monitored scope does not declare excluded devices offline.
- Mass disappearance and missing scanner interface result in an observability warning, not an alert flood.

### Ports and services

- Open to closed, closed to open, and open to filtered retain accurate states.
- A port outside coverage, an ambiguous aggregate result, or a timed-out host does not create a closure.
- A changed profile does not fabricate port changes.
- Device offline does not remove its last-known port inventory.
- Version enrichment does not replace a probed result with an empty guess or create repetitive false changes.
- Many real service start/stop changes remain searchable in history with **zero Pushover deliveries**, including digests and recovery notifications.
- Malicious-looking service banners and hostnames render as text, never executable markup.

### Jobs, notifications, and operations

- Two web processes cannot create duplicate scheduled jobs; two workers cannot apply the same leased job.
- A stale worker/result is fenced out; a crash between event creation and delivery does not lose the outbox record.
- A scan never holds a write lock for its full execution time.
- Ambiguous provider responses, rate limiting, invalid credentials, and internet outages are visible and bounded.
- Muting and cooldown preserve history without replaying suppressed messages.
- An unsent outage superseded by recovery is not delivered later as a current outage.
- Database backup during scanning restores successfully with consistent event/outbox state.
- Retention does not break device history links or remove evidence needed by retained events.
- Authentication, CSRF, scope/port validation, session invalidation, and secret redaction are tested.

Use recorded XML fixtures, fake clocks, a fake Nmap executable, and a mock Pushover transport in CI. Live LAN scanning and real notifications are opt-in acceptance activities, never ordinary test-suite side effects.

## 14. Overall definition of done

Version 1 is complete when a clean deployment can be configured, authenticated, baselined, and operated through the UI; scheduled discovery and port scans survive restarts; watched-device presence notifications are reliable; port/service history is accurate and never alerts; failures/freshness are visible; and backup/restore and upgrade instructions have been exercised.

Known limitations must be documented: polling blind spots, incomplete device identification, MAC changes, limited initial port scope, lack of IPv6/UDP coverage, and the distinction between last-known state and current evidence.

## 15. Starting the next implementation session

Suggested opening request:

> Read NETWORK_DRAGON_PLAN.md and implement Network Dragon in this workspace. Follow the confirmed requirements, especially that port/service changes are logged and displayed but never trigger Pushover notifications. Use the proposed architecture and defaults unless repository evidence exposes a better choice. Start with the project skeleton and a fixture-backed scanning-to-database-to-UI vertical slice, then progress through the implementation phases. Do not copy NetAlertX code. Do not scan live networks or send real notifications until the target scope and credentials are explicitly configured for those actions. Keep a short progress document with completed work, verification results, decisions, and remaining tasks so future sessions can continue.

Before real deployment, obtain the CIDR/interface, management hostname/TLS approach, Linux VM details, and Pushover credentials through an appropriate secret-entry method. These are deployment inputs, not blockers for implementing and testing against fixtures.

## 16. Primary references

These references inform specific integration decisions; verify current compatibility during implementation.

- Nmap structured output: https://nmap.org/book/output-formats-xml-output.html
- Nmap discovery behavior and privilege differences: https://nmap.org/book/man-host-discovery.html
- Nmap port-state semantics: https://nmap.org/book/man-port-scanning-basics.html
- Pushover message API, priorities, errors, and limits: https://pushover.net/api
- SQLite consistent online backups: https://www.sqlite.org/backup.html
- Docker host-network/sysctl restrictions: https://docs.docker.com/reference/cli/docker/container/run/#currently-supported-sysctls

This plan is an independent design for the stated use case, not a claim that the proposed application already exists or has been security-reviewed.
