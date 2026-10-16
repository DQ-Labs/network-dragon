# Architecture and decisions

The proposed stack is implemented: Python/FastAPI, Pydantic validation, SQLAlchemy 2, SQLite WAL, Alembic, React/TypeScript/Vite/Tailwind, Lucide, TanStack Query, pytest, and Playwright. `uv.lock` and `frontend/package-lock.json` are the resolved dependency contracts. There is no Redis, external database, scheduler in the web process, or copied upstream application code.

```text
Browser -> HTTPS proxy -> unprivileged web -> SQLite <- one worker -> Nmap
                                                        |
                                                        +-> Pushover HTTPS
```

`domain/ingest.py` applies one normalized run, projections, immutable events, and eligible outbox entries inside a short transaction. Fixture imports and worker results share this path. Scan IDs deduplicate applications; observation times fence late evidence. Device UUIDs are independent of addresses. MAC evidence is network-scoped; missing MACs create visibly provisional identities. Conflicting identities within one scan are withheld and recorded on the run. Address reuse closes bindings without merging devices. Explicit aliases preserve their original observations and disable independent presence monitoring; canonical identity drives subsequent presence.

Discovery is the only presence evidence. The default discovery job covers the entire configured network. Port results never create devices, infer presence, or close unscanned ports. Explicit observations and provably unambiguous aggregates are compared; aggregate storage is compact. Newly observed ports are marked baseline. Probed service evidence survives subsequent missing/table-only evidence, and missing version fields do not fabricate changes.

Events carry compact before/after evidence independent of retained raw detail. Presence event eligibility is a fixed allowlist in `domain/policy.py`. Unknown types, scanner state, identity changes, ports, versions, and digests are ineligible. Optional scanner-health notifications were deliberately left disabled and unimplemented; health is visible in the UI. The dispatcher checks the allowlist again, checks current watch/mute/scope/episode state, and suppresses stale outages. Recovery requires accepted delivery of the matching outage. Ordinary priority only. Provider bodies and exception strings are not persisted; only sanitized outcomes. Ambiguous provider acceptance can still duplicate on retry: external delivery is not exactly once.

Jobs have owners, lease generations, deadlines, cancellation requests, and explicit terminal status. The worker has a separate singleton lease. Scheduled windows are unique, active manual requests coalesce, and stale queued windows expire. A bounded background executor keeps heartbeat renewal and notification delivery alive during one Nmap process. No database write transaction spans Nmap or HTTPS. Discovery jobs have priority; a manually requested full TCP job can still occupy the single scanner for its explicit budget.

Authentication uses Argon2id and random opaque server-side sessions, stored as token hashes. A signing/session secret is unnecessary because no client-side signed session payload is used. Sessions rotate on login, expire after 12 hours, and all invalidate on password change/restore. Mutations require CSRF headers; cross-origin mutations are rejected; login limits live in SQLite. Production cookies are Secure/HttpOnly/SameSite=Strict. Proxy forwarding is trusted only from explicitly configured numeric IPs.

Nonsecret installation settings live in a validated TOML file, rather than editable rows with a second configuration authority. UI reports them, while annotations, scope enablement, baseline review, profiles, delivery pause, and aliases have audited API mutations. Pushover secrets remain environment/file inputs. Raw XML is transient and size-bounded; normalized evidence is retained instead of keeping seven days of raw artifacts. This reduces disk and banner exposure, but means raw XML replay requires retaining the original fixture externally.

Primary integration references reviewed: [Nmap XML](https://nmap.org/book/output-formats-xml-output.html), [Pushover API](https://pushover.net/api), [FastAPI version pinning](https://fastapi.tiangolo.com/deployment/versions/). These inform format/protocol handling; they do not constitute production validation of this implementation.
