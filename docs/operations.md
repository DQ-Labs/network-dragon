# Operations

Use `NETWORK_DRAGON_CONFIG` consistently for web, worker, and CLI. `init` is the explicit migration command; startup never performs destructive schema work. The initial migration contains frozen DDL independent of future ORM changes. Create a new migration for subsequent schema changes; do not regenerate released history.

The worker schedules configured live scopes only. An empty allowlist or disabled live flag fails closed at both queue and execution. Windows live execution is rejected. `queue-live --network UUID --target CIDR --profile discovery` is an explicit manual queue operation, not a synchronous web scan. Routine ports are configurable in TOML; changing coverage produces a new immutable profile on worker restart. Full TCP and version enrichment are manual profiles.

The Scans page exposes run coverage, Nmap version, profile revision, evidence provenance, and sanitized diagnostics. Raw stdout is limited to 8 MiB and stderr to 64 KiB, in a private temporary directory removed after use. Host timeouts, process deadlines, cancellation, parse errors, and suspect discovery never count as qualifying absence. Scanner-health notification delivery is not implemented; inspect health in the UI. Acknowledging a mass-disappearance warning records review, but never overrides the guard or converts uncertain evidence into absence.

## Backup and restore

`network-dragon backup` uses SQLite's online backup API, checks integrity, and produces a timestamped `.db` plus JSON manifest with SHA-256, schema/application versions, and nonsecret configuration. It keeps seven generations. Protect this directory: backups include inventory and password hashes. Back up provider secret files separately under administrator control.

`network-dragon restore PATH/dragon-TIMESTAMP.db NEW-DATABASE-PATH` verifies the manifest, refuses an existing destination, checks integrity, invalidates sessions, expires queued/running jobs, removes queued test requests, pauses delivery, and suppresses old unsent messages. Stop both services, review the restored file, point the private TOML at it, then start web before worker. Review all pending policy/state before resuming **future** delivery. Never copy only the live WAL database file.

The worker attempts batched retention hourly and a backup daily during idle scan periods. `retention` and `backup` CLI commands are available for controlled maintenance. A database too large to back up within the worker's lease budget needs independent operational scheduling; measure this before deployment. Retention defaults: detailed host/port evidence 30 days, events 365 days, delivery attempts 90 days. Referenced scans/current-state evidence survive pruning; accepted ongoing outage records survive to preserve recovery eligibility. Identity/audit records remain; long-term audit growth needs pilot measurement.

Upgrade: verify a fresh backup; stop worker and web; install the locked new build; run `init`; start web and check readiness/login; restart worker; verify fresh discovery before resuming delivery. Rollback for a destructive migration means restoring the pre-upgrade backup, not merely launching an old image.

## Current limitations

Polling misses short-lived services. IPv6/UDP, arbitrary Nmap arguments, NSE scripts, vulnerability scanning, and OS detection are unsupported. Nmap can miss devices that do not answer the configured discovery method. Identity aliases are administrator decisions and do not combine presence across multiple active NICs. Port guesses are distinguished from active detection. Last-known service identity can be older than its most recent port-state observation.

Runtime settings require a TOML edit and process restart; the Settings screen is the status view. Browser timestamps currently use the browser's local timezone (installation timezone is retained as configuration metadata). Notification delivery cannot promise exactly once across ambiguous provider acceptance. A real whole-VLAN outage may initially remain an observability warning. The scanner's own address is excluded from live port execution because its local route is not on-link.
