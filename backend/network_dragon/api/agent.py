"""Read-only MCP tools for local agents, served as stateless streamable HTTP at /mcp."""

import functools
import json
import time
from datetime import UTC, datetime
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from network_dragon.api.queries import (
    delivery_paused,
    device_counts,
    device_detail,
    device_query,
    enrich_devices,
    event_query,
    jobs_query,
    page,
    runs_query,
)
from network_dragon.auth.service import api_token, bearer
from network_dragon.persistence.models import CurrentPort, Device, Network, WorkerLease

Offset = Annotated[int, Field(ge=0)]
Limit = Annotated[int, Field(ge=1, le=100)]
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


def iso(value):
    return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def prune(value):
    if isinstance(value, dict):
        value = {k: prune(v) for k, v in value.items()}
        return {k: v for k, v in value.items() if v is not None and v != ""}
    return [prune(v) for v in value] if isinstance(value, list) else value


def dump(value):
    return json.dumps(prune(value), separators=(",", ":"), default=str)


def paged(data, items):
    end = data["offset"] + len(items)
    return {
        "total": data["total"],
        "next_offset": end if end < data["total"] else None,
        "items": items,
    }


def summary(item):
    flags = {
        "stale": item["stale"],
        "watched": item["watched"],
        "unreviewed": not item["acknowledged"],
        "unmonitored": not item["monitored"],
        "archived": item["archived"],
        "muted": (item["mute_until"] or 0) > time.time(),
    }
    return {
        "id": item["id"],
        "name": item["name"],
        "hostname": item["hostname"],
        "ip": item["ip"],
        "mac": item["mac"],
        "presence": item["presence"],
        "open_ports": item["open_ports"],
        "last_seen": iso(item["last_seen"]),
        "flags": [flag for flag, on in flags.items() if on] or None,
    }


def service(facts):
    return " ".join(filter(None, (facts.get(k) for k in ("name", "product", "version"))))


class Guard:
    """Admit only requests carrying a valid API token; cookies never authorize /mcp."""

    def __init__(self, engine, app):
        self.engine, self.app = engine, app

    def valid(self, raw):
        with Session(self.engine) as session:
            return api_token(session, raw) is not None

    async def __call__(self, scope, receive, send):
        raw = bearer(Request(scope))
        if not raw or not await run_in_threadpool(self.valid, raw):
            response = JSONResponse(
                {"detail": "Bearer API token required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            return await response(scope, receive, send)
        if scope["method"] != "POST":
            # Stateless JSON mode has no server-initiated stream or session to delete.
            response = JSONResponse(
                {"detail": "Use POST"}, status_code=405, headers={"Allow": "POST"}
            )
            return await response(scope, receive, send)
        await self.app(scope, receive, send)


def agent_server(engine, config):
    server = FastMCP(
        "network-dragon",
        instructions="Read-only IPv4/TCP inventory of the monitored network. Times are UTC.",
        stateless_http=True,
        json_response=True,
        log_level="WARNING",
        # Host/Origin policy lives in the app middleware, and bearer tokens defeat DNS rebinding.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    def tool(fn):
        @functools.wraps(fn)
        async def threaded(*args, **kwargs):
            return await run_in_threadpool(fn, *args, **kwargs)

        return server.tool(annotations=READ_ONLY, structured_output=False)(threaded)

    def resolve(session, device):
        found = session.get(Device, device) or session.scalar(
            select(Device)
            .where(Device.ip == device, Device.canonical_id.is_(None))
            .order_by(Device.last_seen.desc())
        )
        if not found:
            raise ToolError(f"No device with id or IP {device!r}")
        return found

    @tool
    def list_devices(
        presence: Literal["online", "offline", "suspected_missing", "unknown"] | None = None,
        query: str = "",
        offset: Offset = 0,
        limit: Limit = 25,
    ) -> str:
        """List devices by IP. `query` matches name, hostname, IP or MAC."""
        with Session(engine) as session:
            data = page(session, device_query(query, presence or ""), offset, limit)
            items = enrich_devices(session, config, data["items"])
            return dump(paged(data, [summary(i) for i in items]))

    @tool
    def get_device(device: str) -> str:
        """Device detail with address history and current TCP ports. `device` is an id or IP."""
        with Session(engine) as session:
            item = device_detail(session, config, resolve(session, device))
            ports = session.scalars(
                select(CurrentPort)
                .where(CurrentPort.device_id == item["id"])
                .order_by(CurrentPort.port)
                .limit(200)
            )
            return dump(
                summary(item)
                | {
                    "network_id": item["network_id"],
                    "confidence": item["confidence"],
                    "notes": item["notes"],
                    "first_seen": iso(item["first_seen"]),
                    "canonical_id": item["canonical_id"],
                    "aliases": [a["id"] for a in item["aliases"]] or None,
                    "addresses": [
                        {
                            "address": a["address"],
                            "first_seen": iso(a["first_seen"]),
                            "last_seen": iso(a["last_seen"]),
                            "ended": iso(a["ended_at"]),
                        }
                        for a in item["addresses"]
                    ],
                    "ports": [
                        {
                            "port": p.port,
                            "state": p.state,
                            "service": service(p.facts),
                            "seen": iso(p.observed_at),
                        }
                        for p in ports
                    ],
                }
            )

    @tool
    def recent_events(
        category: Literal["presence", "ports", "identity", "system"] | None = None,
        device: str = "",
        since: str = "",
        offset: Offset = 0,
        limit: Limit = 25,
    ) -> str:
        """Newest events first. `device` is an id or IP; `since` is ISO-8601 (UTC if no zone)."""
        try:
            start = datetime.fromisoformat(since) if since else None
        except ValueError as exc:
            raise ToolError("`since` must be an ISO-8601 timestamp") from exc
        if start and not start.tzinfo:
            start = start.replace(tzinfo=UTC)
        with Session(engine) as session:
            device_id = resolve(session, device).id if device else ""
            stmt = event_query(category or "", device_id, since=start and start.timestamp())
            data = page(session, stmt, offset, limit)
            items = [
                {
                    "at": iso(e["at"]),
                    "type": e["type"],
                    "device_id": e["device_id"],
                    "baseline": e["baseline"] or None,
                    "facts": e["facts"],
                }
                for e in data["items"]
            ]
            return dump(paged(data, items))

    @tool
    def network_status() -> str:
        """Networks and scanner health, worker lease, device counts and delivery pause state."""
        with Session(engine) as session:
            lease = session.get(WorkerLease, 1)
            return dump(
                {
                    "networks": [
                        {
                            "id": n.id,
                            "name": n.name,
                            "cidr": n.cidr,
                            "mode": n.mode,
                            "enabled": n.enabled,
                            "baseline_review": n.baseline,
                            "health": n.health,
                            "health_reason": n.health_reason,
                            "last_discovery": iso(n.last_discovery),
                        }
                        for n in session.scalars(select(Network).order_by(Network.name))
                    ],
                    "worker": {
                        "alive": lease.expires > time.time(),
                        "heartbeat": iso(lease.heartbeat),
                        "lease_expires": iso(lease.expires),
                    }
                    if lease
                    else {"alive": False},
                    "counts": device_counts(session),
                    "delivery_paused": delivery_paused(session),
                    "live_scanning": config.live_scanning,
                    "discovery_seconds": config.discovery_seconds,
                    "ports_seconds": config.ports_seconds,
                }
            )

    @tool
    def scan_history(offset: Offset = 0, limit: Annotated[int, Field(ge=1, le=50)] = 10) -> str:
        """Newest scan jobs (queued work) and runs (ingested results)."""
        with Session(engine) as session:
            jobs, runs = (
                page(session, jobs_query(), offset, limit),
                page(session, runs_query(), offset, limit),
            )
            return dump(
                {
                    "jobs": paged(
                        jobs,
                        [
                            {
                                "id": j["id"],
                                "network_id": j["network_id"],
                                "profile": j["profile_id"],
                                "target": j["target"],
                                "status": j["status"],
                                "created": iso(j["created_at"]),
                                "finished": iso(j["finished_at"]),
                                "error": j["error"],
                                "cancel_requested": j["cancel_requested"] or None,
                            }
                            for j in jobs["items"]
                        ],
                    ),
                    "runs": paged(
                        runs,
                        [
                            {
                                "id": r["id"],
                                "network_id": r["network_id"],
                                "kind": r["kind"],
                                "source": r["source"],
                                "status": r["status"],
                                "observed": iso(r["observed_at"]),
                                "health_reason": r["health_reason"],
                                "ports_covered": len(r["coverage"].get("ports", [])),
                                "identity_conflicts": len(
                                    r["coverage"].get("identity_conflicts", [])
                                ),
                            }
                            for r in runs["items"]
                        ],
                    ),
                }
            )

    return server, Guard(engine, server.streamable_http_app())
