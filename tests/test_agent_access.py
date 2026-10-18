import json
import threading
import time

import anyio
import httpx
import pytest
import uvicorn
from conftest import xml
from fastapi.testclient import TestClient
from network_dragon.api.app import create_app
from network_dragon.auth.service import create_token, revoke_token, set_password
from network_dragon.persistence.db import transaction
from network_dragon.persistence.models import (
    ApiToken,
    Audit,
    DeliveryAttempt,
    Device,
    Event,
    Job,
    Outbox,
    Setting,
    WorkerLease,
)
from sqlalchemy import delete, event, select, update
from sqlalchemy.orm import Session

ACCEPT = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def client(env):
    with transaction(env[0]) as s:
        set_password(s, "fixture-password-only")
    with TestClient(create_app(env[1], env[0])) as client:
        yield client


@pytest.fixture
def token(env):
    with transaction(env[0]) as s:
        raw = create_token(s, "agent")
    return {"Authorization": f"Bearer {raw}"}


@pytest.fixture
def inventory(env, ingest_run):
    now = time.time()
    hosts = [
        ("192.0.2.1", "02:00:00:00:00:01", [], "Raspberry Pi Trading"),
        ("192.0.2.2", None, []),
    ]
    ingest_run(xml(hosts, at=now))
    ingest_run(
        xml(
            [("192.0.2.1", None, [(22, "open", {"name": "ssh", "product": "OpenSSH"})])],
            coverage="22,80",
            at=now + 1,
        ),
        kind="ports",
    )
    with transaction(env[0]) as s:
        s.scalar(select(Device).where(Device.ip == "192.0.2.1")).name = "nas"
        s.add(WorkerLease(owner="w1", generation=1, expires=now + 60, heartbeat=now))
        s.add(Setting(key="delivery_paused", value={"paused": True}))
    with Session(env[0]) as s:
        return {d.ip: d.id for d in s.scalars(select(Device))}


def sign_in(client):
    response = client.post("/api/v1/session", json={"password": "fixture-password-only"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf"]}


def rpc(client, method, params=None, headers=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers={**ACCEPT, **(headers or {})})


def call(client, token, name, **arguments):
    response = rpc(client, "tools/call", {"name": name, "arguments": arguments}, token)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert not result.get("isError"), result
    assert "structuredContent" not in result
    return json.loads(result["content"][0]["text"])


def test_token_reads_devices_events_and_stamps_usage_cheaply(client, env, token, inventory):
    assert client.get("/api/v1/devices").status_code == 401
    devices = client.get("/api/v1/devices", headers=token).json()
    assert devices["total"] == 2 and devices["items"][0]["name"] == "nas"
    assert devices["items"][0]["vendor"] == "Raspberry Pi Trading"
    search = client.get("/api/v1/devices", params={"q": "Pi Trading"}, headers=token).json()
    assert [d["ip"] for d in search["items"]] == ["192.0.2.1"]
    assert client.get("/api/v1/events", headers=token).json()["total"] >= 2
    assert client.get(f"/api/v1/devices/{inventory['192.0.2.1']}", headers=token).json()["ip"]
    with Session(env[0]) as s:
        first = s.scalar(select(ApiToken.last_used_at))
    assert first and first <= time.time()
    client.get("/api/v1/overview", headers=token)
    with transaction(env[0]) as s:
        assert s.scalar(select(ApiToken.last_used_at)) == first
        s.execute(update(ApiToken).values(last_used_at=first - 61))
    client.get("/api/v1/overview", headers=token)
    with Session(env[0]) as s:
        assert s.scalar(select(ApiToken.last_used_at)) >= first


def test_token_refused_for_mutations_and_session_endpoints(client, env, token, inventory):
    device = f"/api/v1/devices/{inventory['192.0.2.1']}"
    password = {"current_password": "fixture-password-only", "new_password": "another-password-1"}
    attempts = [
        ("POST", "/api/v1/scans", {"network_id": env[2], "target": "192.0.2.1"}),
        ("PATCH", device, {"watched": True}),
        ("DELETE", "/api/v1/session", None),
        ("POST", "/api/v1/notifications/pause", {"paused": False}),
        ("POST", "/api/v1/session", {"password": "fixture-password-only"}),
        ("PUT", "/api/v1/session/password", password),
        ("GET", "/api/v1/session", None),
    ]
    for method, path, body in attempts:
        response = client.request(method, path, json=body, headers=token)
        assert response.status_code == 403, (method, path)
    # A bearer header is never combined with a cookie session to gain write access.
    csrf = sign_in(client)
    assert (
        client.patch(device, json={"watched": True}, headers={**token, **csrf}).status_code == 403
    )
    with Session(env[0]) as s:
        assert not s.get(Device, inventory["192.0.2.1"]).watched
        assert not s.scalar(select(Job))
    assert client.get("/api/v1/session", headers=csrf).status_code == 200


def test_revoked_expired_and_unknown_tokens_refused(client, env, token, inventory):
    with transaction(env[0]) as s:
        expiring = create_token(s, "expiring", expires_days=1)
        with pytest.raises(ValueError, match="already exists"):
            create_token(s, "agent")
    expired = {"Authorization": f"Bearer {expiring}"}
    assert client.get("/api/v1/devices", headers=expired).status_code == 200
    with transaction(env[0]) as s:
        s.execute(update(ApiToken).where(ApiToken.name == "expiring").values(expires_at=1))
        revoke_token(s, "agent")
    for headers in (token, expired, {"Authorization": "Bearer nd_unknown"}):
        response = client.get("/api/v1/devices", headers=headers)
        assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
        assert rpc(client, "tools/list", headers=headers).status_code == 401
    with Session(env[0]) as s:
        assert [(a.action, a.subject) for a in s.scalars(select(Audit).order_by(Audit.at))] == [
            ("token.created", "agent"),
            ("token.created", "expiring"),
            ("token.revoked", "agent"),
        ]
        assert all(len(t.token_hash) == 64 for t in s.scalars(select(ApiToken)))
        assert s.scalar(select(ApiToken.token_hash).where(ApiToken.name == "expiring")) != expiring


def test_cookie_csrf_flow_unchanged(client, inventory):
    device = f"/api/v1/devices/{inventory['192.0.2.1']}"
    assert client.get("/api/v1/session").status_code == 401
    csrf = sign_in(client)
    assert client.get("/api/v1/session").json() == {"csrf": csrf["X-CSRF-Token"]}
    assert client.get("/api/v1/devices").json()["total"] == 2
    assert client.patch(device, json={"watched": True}).status_code == 403
    assert client.patch(device, json={"watched": True}, headers=csrf).status_code == 200
    assert client.get(device).json()["watched"] is True
    # A cookie session is not an MCP credential.
    assert rpc(client, "tools/list").status_code == 401
    assert client.delete("/api/v1/session", headers=csrf).status_code == 200
    assert client.get("/api/v1/devices").status_code == 401


def test_openapi_requires_auth_and_docs_stay_disabled(client, token):
    assert client.get("/api/v1/openapi.json").status_code == 401
    schema = client.get("/api/v1/openapi.json", headers=token).json()
    assert "/api/v1/devices" in schema["paths"] and "/api/v1/openapi.json" not in schema["paths"]
    sign_in(client)
    assert client.get("/api/v1/openapi.json").json()["info"]["title"] == "Network Dragon"
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert "swagger" not in client.get(path).text.lower()
        assert "redoc" not in client.get(path).text.lower()


def test_mcp_requires_bearer_and_rejects_cross_site_browsers(client, token):
    response = rpc(client, "tools/list")
    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
    assert rpc(client, "tools/list", headers={"Authorization": "Basic eDp5"}).status_code == 401
    hostile = {**token, "Origin": "https://evil.example"}
    assert rpc(client, "tools/list", headers=hostile).status_code == 403
    assert client.get("/mcp", headers=hostile).status_code == 403
    assert client.get("/mcp").status_code == 401
    assert client.get("/mcp", headers=token).status_code == 405
    assert client.delete("/mcp", headers=token).status_code == 405
    cross = {**token, "Sec-Fetch-Site": "cross-site"}
    assert rpc(client, "tools/list", headers=cross).status_code == 403
    same = {**token, "Origin": "http://testserver"}
    assert rpc(client, "tools/list", headers=same).status_code == 200
    # Agents send no Origin at all.
    hello = rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"},
        },
        token,
    )
    assert hello.status_code == 200 and hello.headers["cache-control"] == "no-store"
    assert hello.json()["result"]["serverInfo"]["name"] == "network-dragon"
    tools = rpc(client, "tools/list", headers=token).json()["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "list_devices",
        "get_device",
        "recent_events",
        "network_status",
        "scan_history",
    }
    assert all(t["annotations"]["readOnlyHint"] for t in tools)


def test_mcp_tools_return_compact_inventory(client, env, token, inventory):
    devices = call(client, token, "list_devices")
    assert devices["total"] == 2 and "next_offset" not in devices
    nas = devices["items"][0]
    assert nas["name"] == "nas" and nas["ip"] == "192.0.2.1" and nas["presence"] == "online"
    assert (
        nas["open_ports"] == 1 and nas["last_seen"].endswith("Z") and "unreviewed" in nas["flags"]
    )
    paged = call(client, token, "list_devices", limit=1, presence="online")
    assert paged["total"] == 2 and paged["next_offset"] == 1 and len(paged["items"]) == 1
    assert call(client, token, "list_devices", query="02:00:00:00:00:01")["total"] == 1
    assert nas["vendor"] == "Raspberry Pi Trading" and "vendor" not in devices["items"][1]
    assert call(client, token, "list_devices", query="raspberry")["total"] == 1
    assert call(client, token, "list_devices", presence="offline")["total"] == 0

    detail = call(client, token, "get_device", device="192.0.2.1")
    assert detail["id"] == inventory["192.0.2.1"] and detail["mac"] == "02:00:00:00:00:01"
    assert detail["vendor"] == "Raspberry Pi Trading"
    assert detail["ports"] == [
        {"port": 22, "state": "open", "service": "ssh OpenSSH", "seen": detail["ports"][0]["seen"]}
    ]
    assert (
        detail["addresses"][0]["address"] == "192.0.2.1" and "ended" not in detail["addresses"][0]
    )
    assert call(client, token, "get_device", device=inventory["192.0.2.2"])["ip"] == "192.0.2.2"
    missing = rpc(
        client, "tools/call", {"name": "get_device", "arguments": {"device": "203.0.113.9"}}, token
    ).json()["result"]
    assert missing["isError"] and "No device" in missing["content"][0]["text"]

    events = call(client, token, "recent_events")
    types = {e["type"] for e in events["items"]}
    assert {"device.new", "port.baseline"} <= types
    ports = call(client, token, "recent_events", category="ports", device="192.0.2.1")
    assert ports["total"] == 1 and ports["items"][0]["facts"]["port"] == 22
    assert all(e["device_id"] == inventory["192.0.2.1"] for e in ports["items"])
    assert call(client, token, "recent_events", since="2999-01-01T00:00:00")["total"] == 0
    assert (
        call(client, token, "recent_events", since="1970-01-01T00:00:00Z")["total"]
        == events["total"]
    )

    status = call(client, token, "network_status")
    assert status["networks"][0]["cidr"] == "192.0.2.0/29"
    assert status["networks"][0]["health"] == "healthy"
    assert status["worker"]["alive"] is True and status["delivery_paused"] is True
    assert status["counts"]["online"] == 2 and status["counts"]["total"] == 2

    history = call(client, token, "scan_history", limit=1)
    assert history["runs"]["total"] == 2 and history["runs"]["next_offset"] == 1
    assert history["runs"]["items"][0]["kind"] == "ports"
    assert history["runs"]["items"][0]["ports_covered"] == 2
    assert history["jobs"] == {"total": 0, "items": []}


def test_mcp_with_official_client_over_http(env, token, inventory):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    server = uvicorn.Server(
        uvicorn.Config(create_app(env[1], env[0]), host="127.0.0.1", port=0, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]

    async def session():
        async with (
            httpx.AsyncClient(headers=token, timeout=10) as http,
            streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=http) as (r, w, _),
            ClientSession(r, w) as mcp,
        ):
            await mcp.initialize()
            result = await mcp.call_tool("get_device", {"device": "192.0.2.1"})
            return json.loads(result.content[0].text)

    try:
        assert anyio.run(session)["name"] == "nas"
    finally:
        server.should_exit = True
        thread.join(5)


def test_search_escapes_like_wildcards(client, env, ingest_run, token):
    ingest_run(xml())
    with transaction(env[0]) as s:
        s.scalar(select(Device)).name = "100%_done"
        s.add(
            Device(
                network_id=env[2],
                identity="other",
                ip="192.0.2.9",
                name="100xxdone",
                first_seen=1,
                last_seen=1,
                last_evidence=1,
            )
        )
    find = lambda q: client.get("/api/v1/devices", params={"q": q}, headers=token).json()  # noqa: E731
    assert [d["name"] for d in find("100%_done")["items"]] == ["100%_done"]
    assert find("%")["total"] == 1 and find("_d")["total"] == 1 and find("x_")["total"] == 0
    assert find("100")["total"] == 2
    events = lambda q: client.get("/api/v1/events", params={"q": q}, headers=token).json()  # noqa: E731
    assert events("device%new")["total"] == 0 and events("device.new")["total"] == 1
    assert events("192.0.2_1")["total"] == 0


def test_notifications_batch_event_and_attempt_lookups(client, env, ingest_run):
    ingest_run(xml([(f"192.0.2.{i}", f"02:00:00:00:00:0{i}", []) for i in range(1, 6)]))
    with transaction(env[0]) as s:
        s.execute(delete(Outbox))
        for i, e in enumerate(s.scalars(select(Event).order_by(Event.at, Event.id))):
            entry = Outbox(event_id=e.id, next_attempt=i, status="failed")
            s.add(entry)
            s.flush()
            s.add_all(DeliveryAttempt(outbox_id=entry.id, at=n, outcome="x") for n in range(i))
    sign_in(client)
    queries = []

    def capture(_conn, _cursor, statement, *_):
        if any(f"FROM {t}" in statement for t in ("events", "delivery_attempts")):
            queries.append(statement)

    event.listen(env[0], "before_cursor_execute", capture)
    try:
        result = client.get("/api/v1/notifications", params={"limit": 5}).json()
    finally:
        event.remove(env[0], "before_cursor_execute", capture)
    assert len(queries) == 2 and len(result["items"]) == 5 and result["total"] > 5
    for item in result["items"]:
        assert item["event"]["id"] == item["event_id"]
        assert len(item["delivery_attempts"]) == item["next_attempt"]
        assert [a["at"] for a in item["delivery_attempts"]] == list(
            range(int(item["next_attempt"]))
        )
