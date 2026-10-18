# Network Dragon

Independent, self-hosted IPv4/TCP inventory built with FastAPI, SQLite, React, and Nmap. Presence and service observations are separate. **Port/service changes are recorded and displayed, and can never generate Pushover notifications.** No NetAlertX source or assets are used.

This is a working fixture-verified implementation, not a production-certified release. Linux scanning permissions, container execution, firewall policy, and the real VLAN pilot still require validation. See [PROGRESS.md](PROGRESS.md) for the exact handoff.

## Start locally (PowerShell)

Python 3.12–3.14 and Node 24 are supported targets; this workspace was verified with Python 3.14.7 and Node 24.21.0. Install `uv` 0.13.1 with your normal Python tooling, then:

```powershell
uv sync --frozen
Push-Location frontend
npm ci
npm run build
Pop-Location
$env:NETWORK_DRAGON_CONFIG = "$PWD/deploy/config.dev.toml"
uv run network-dragon init
uv run network-dragon create-admin
uv run network-dragon import-fixture tests/fixtures/nmap/discovery.xml --cidr 192.0.2.0/24
uv run network-dragon import-fixture tests/fixtures/nmap/ports.xml --cidr 192.0.2.0/24 --kind ports
uv run network-dragon import-fixture tests/fixtures/nmap/port-changes.xml --cidr 192.0.2.0/24 --kind ports
uv run network-dragon web
```

Open [the local app](http://127.0.0.1:8000). The administrator command uses hidden password entry; there is no default password. The bundled fixtures use documentation-only addresses and fixed timestamps, so they correctly become **stale** as time passes. Reimporting a file is idempotent. Development HTTP is restricted to localhost. No worker is needed to browse fixtures.

If `uv` was installed inside `.venv`, use `.\.venv\Scripts\uv.exe` in place of `uv`. On this sandboxed Windows host, set `TEMP` and `TMP` to the workspace `.tmp` folder for installation/testing. API and browser tests need loopback socket access.

For frontend development, run `npm run dev` in `frontend` alongside the backend; Vite proxies the API. The production build is served by FastAPI from the same origin.

## Verify

```powershell
uv run pytest -q
uv run ruff check backend tests
uv run ruff format --check backend tests
uv run mypy backend/network_dragon
Push-Location frontend
npm run format:check
npm run build
npx playwright install chromium
Pop-Location
```

Run `uv run python scripts/check_browser.py` for browser verification. It generates a unique test password, prepares a separate fixture database, starts the app on localhost port 8765, runs Playwright, and stops its server. Screenshots are saved under `artifacts/`; it never changes a real inventory or enables external actions. For manual browser-test setup, `scripts/make_demo.py --browser` accepts `DRAGON_TEST_PASSWORD` and writes `.tmp/browser.toml`.

## Agent access

Local AI agents can read the inventory through a remote MCP endpoint at `/mcp` (streamable HTTP, stateless JSON) and the JSON API, using **read-only API tokens**. Tokens work only for `GET`/`HEAD` on `/api/v1/*` and for `/mcp`; any other method gets 403, and they never work on `/api/v1/session*` (sign-in, sign-out, password change). The database stores only each token's SHA-256 digest. Creating and revoking tokens is audited.

```bash
network-dragon init                                    # applies migration 0002 when upgrading
network-dragon create-token laptop-agent --expires-days 90   # prints the token once
network-dragon list-tokens                             # name, created, last used (to the minute), expiry
network-dragon revoke-token laptop-agent
```

Connect Claude Code:

```bash
claude mcp add --transport http network-dragon https://dragon.lonk-dorian.ts.net:8443/mcp --header "Authorization: Bearer <token>"
```

The MCP tools (`list_devices`, `get_device`, `recent_events`, `network_status`, `scan_history`) return compact JSON with UTC ISO-8601 times and paginate with `offset`/`limit`. A device can be named by id or current IP. Query the API with curl:

```bash
curl -H "Authorization: Bearer <token>" "https://dragon.lonk-dorian.ts.net:8443/api/v1/devices?presence=online&limit=20"
```

The OpenAPI schema is at `/api/v1/openapi.json` and needs a session or token; `/docs` and `/redoc` stay disabled. `/mcp` refuses requests without a valid bearer token (401) and any browser `Origin` other than the app's own (403). Agents that send no `Origin` are accepted. With `allow_http_local = true`, `/mcp` is limited to localhost like the rest of the app.

## Operating model

- One administrator and one leased worker. The web process only queues jobs.
- Discovery every 120 seconds; routine TCP ports every 900 seconds. Default ports are Nmap's top 1,000; configured explicit ports produce a new immutable profile.
- Offline requires three consecutive qualifying misses **and** five minutes since last positive discovery. Scanner failures break the miss sequence.
- A mass-disappearance guard withholds negative transitions when at least three previously present devices lose at least 80% of their observations.
- Each network starts in baseline review. Watch fixed devices explicitly before enabling delivery.
- Port states and service identity have their own observations and timestamps; lack of evidence never implies closure.
- Notifications use an allowlisted transactional outbox and a second allowlist check at dispatch. Fixture evidence cannot drive the real provider. Explicit test messages use a separate fixed-message request.

See [architecture](docs/architecture.md), [deployment](docs/deployment.md), [operations](docs/operations.md), and [acceptance](docs/acceptance.md). Actual scope, interface, HTTPS management path, VM details, and secrets are deliberately unset.
