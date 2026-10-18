import json
import time

import pytest
from conftest import xml
from fastapi.testclient import TestClient
from network_dragon.api.app import create_app
from network_dragon.auth.service import set_password
from network_dragon.operations.backup import backup, restore
from network_dragon.operations.retention import cleanup
from network_dragon.persistence.db import engine_for, transaction
from network_dragon.persistence.models import Device, Event, HostObservation, Network, Run, Setting
from network_dragon.scanner.validation import ports, scope
from network_dragon.scanner.xml import parse_xml
from network_dragon.worker.queue import acquire, claim, fenced
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session


@pytest.fixture
def browser(env):
    with transaction(env[0]) as s:
        set_password(s, "fixture-password-only")
    with TestClient(create_app(env[1], env[0])) as client:
        yield client


def sign_in(browser):
    response = browser.post("/api/v1/session", json={"password": "fixture-password-only"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf"]}


def test_auth_csrf_and_password_invalidation(browser, env, ingest_run):
    ingest_run(xml())
    assert browser.get("/api/v1/devices").status_code == 401
    headers = sign_in(browser)
    d = browser.get("/api/v1/devices").json()["items"][0]
    assert browser.patch(f"/api/v1/devices/{d['id']}", json={"watched": True}).status_code == 403
    assert (
        browser.patch(
            f"/api/v1/devices/{d['id']}", json={"watched": True}, headers=headers
        ).status_code
        == 200
    )
    assert (
        browser.patch(
            f"/api/v1/devices/{d['id']}", json={"presence": "offline"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        browser.put(
            "/api/v1/session/password",
            json={
                "current_password": "fixture-password-only",
                "new_password": "changed-password-only",
            },
            headers=headers,
        ).status_code
        == 200
    )
    assert browser.get("/api/v1/devices").status_code == 401


def test_cross_origin_login_and_throttle(browser):
    assert (
        browser.post(
            "/api/v1/session",
            json={"password": "fixture-password-only"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    for _ in range(5):
        assert browser.post("/api/v1/session", json={"password": "wrong"}).status_code == 401
    assert (
        browser.post("/api/v1/session", json={"password": "fixture-password-only"}).status_code
        == 429
    )


def test_scope_disabled_unmonitored_not_offline(browser, env, ingest_run):
    ingest_run(xml())
    headers = sign_in(browser)
    assert (
        browser.patch(
            f"/api/v1/networks/{env[2]}", json={"enabled": False}, headers=headers
        ).status_code
        == 200
    )
    d = browser.get("/api/v1/devices").json()["items"][0]
    assert d["monitored"] is False and d["presence"] == "online"


def test_fixture_cannot_queue_live(browser, env):
    headers = sign_in(browser)
    response = browser.post(
        "/api/v1/scans", json={"network_id": env[2], "target": "192.0.2.0/29"}, headers=headers
    )
    assert response.status_code == 422


def test_merge_preserves_original_events(browser, env, ingest_run):
    ingest_run(
        xml([("192.0.2.1", "02:00:00:00:00:01", []), ("192.0.2.2", "02:00:00:00:00:02", [])])
    )
    headers = sign_in(browser)
    devices = browser.get("/api/v1/devices").json()["items"]
    assert (
        browser.post(
            f"/api/v1/devices/{devices[0]['id']}/merge",
            json={"canonical_id": devices[1]["id"], "reason": "Administrator verified alias"},
            headers=headers,
        ).status_code
        == 200
    )
    assert browser.get("/api/v1/devices").json()["total"] == 1
    with Session(env[0]) as s:
        assert s.scalar(select(Event).where(Event.device_id == devices[0]["id"]))


def test_backup_restore_paused_and_history_consistent(env, ingest_run, tmp_path):
    ingest_run(xml())
    destination = backup(env[1])
    restored = tmp_path / "restored.db"
    restore(destination, restored)
    engine = engine_for(str(restored))
    with Session(engine) as s:
        assert s.get(Setting, "delivery_paused").value["paused"]
        assert s.scalar(select(Device))
    engine.dispose()


@pytest.mark.parametrize(
    "manifest, message",
    [
        (None, "Cannot read backup manifest"),
        (b"{broken", "valid UTF-8 JSON"),
        (b"\xff", "valid UTF-8 JSON"),
        (b"[]", "valid SHA-256"),
        (b"{}", "valid SHA-256"),
        (b'{"sha256": 123}', "valid SHA-256"),
        (b'{"sha256": "bad"}', "valid SHA-256"),
        (json.dumps({"sha256": "0" * 64}).encode(), "checksum mismatch"),
    ],
)
def test_restore_rejects_invalid_manifest_before_creating_destination(tmp_path, manifest, message):
    source = tmp_path / "backup.db"
    source.write_bytes(b"backup contents")
    if manifest is not None:
        source.with_suffix(".json").write_bytes(manifest)
    destination = tmp_path / "new" / "restored.db"
    with pytest.raises(ValueError, match=message):
        restore(source, destination)
    assert not destination.parent.exists()
    assert source.read_bytes() == b"backup contents"


def test_restore_reports_missing_database(tmp_path):
    source = tmp_path / "missing.db"
    source.with_suffix(".json").write_text(json.dumps({"sha256": "0" * 64}))
    destination = tmp_path / "restored.db"
    with pytest.raises(ValueError, match="Cannot read backup database"):
        restore(source, destination)
    assert not destination.exists()


def test_device_list_batches_enrichment_and_preserves_pagination(browser, env, ingest_run):
    now = time.time()
    ingest_run(xml(at=now))
    ingest_run(
        xml(
            [("192.0.2.1", None, [(22, "open", {}), (80, "closed", {})])],
            coverage="22,80",
            at=now + 1,
        ),
        kind="ports",
    )
    with transaction(env[0]) as session:
        first = session.scalar(select(Device))
        first.name = "review-device-00"
        first_id = first.id
        unhealthy = Network(name="Unhealthy", cidr="198.51.100.0/24", health="unknown")
        session.add(unhealthy)
        session.flush()
        for i in range(1, 50):
            session.add(
                Device(
                    network_id=unhealthy.id if i == 49 else env[2],
                    identity=f"review-{i}",
                    ip=f"192.0.2.{i + 1}",
                    name=f"review-device-{i:02d}",
                    first_seen=now,
                    last_seen=now,
                    last_evidence=0 if i == 48 else now,
                )
            )
    sign_in(browser)
    queries = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and any(
            f"FROM {table}" in statement for table in ("devices", "networks", "current_ports")
        ):
            queries.append(statement)

    event.listen(env[0], "before_cursor_execute", capture)
    try:
        for limit in (1, 50):
            queries.clear()
            response = browser.get(
                "/api/v1/devices", params={"q": "review-device", "sort": "name", "limit": limit}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 50 and data["limit"] == limit and data["offset"] == 0
            assert len(data["items"]) == limit
            assert len(queries) == 4
            assert data["items"][0]["open_ports"] == 1
            assert data["items"][0]["stale"] is False
        assert all(d["open_ports"] == 0 for d in data["items"][1:])
        assert [d["stale"] for d in data["items"]] == [False] * 48 + [True, True]
        second_page = browser.get(
            "/api/v1/devices",
            params={"q": "review-device", "sort": "name", "offset": 48, "limit": 7},
        ).json()
        assert [d["name"] for d in second_page["items"]] == ["review-device-48", "review-device-49"]
        assert second_page["offset"] == 48 and second_page["limit"] == 7
        queries.clear()
        empty = browser.get("/api/v1/devices", params={"q": "no-such-device"}).json()
        assert empty["items"] == [] and empty["total"] == 0
        assert len(queries) == 2
    finally:
        event.remove(env[0], "before_cursor_execute", capture)
    detail = browser.get(f"/api/v1/devices/{first_id}").json()
    assert detail["open_ports"] == 1 and detail["stale"] is False


def test_retention_preserves_event_evidence(env, ingest_run):
    ingest_run(xml())
    cleanup(env[0], env[1], 1000 + 31 * 86400)
    with Session(env[0]) as s:
        e = s.scalar(select(Event).where(Event.type == "device.new"))
        assert e.facts["ip"] == "192.0.2.1"
        assert e.run_id


def test_retention_drains_backlog_beyond_one_batch(env, ingest_run):
    hosts = [(f"192.0.2.{i}", f"02:00:00:00:00:0{i}", []) for i in range(1, 4)]
    for at in range(1000, 1600, 120):
        ingest_run(xml(hosts, at=at))
    with Session(env[0]) as s:
        assert s.scalar(select(func.count()).select_from(HostObservation)) == 15
    removed = cleanup(env[0], env[1], 1000 + 31 * 86400, batch=2)
    assert removed["host_observations"] == 15
    with Session(env[0]) as s:
        assert s.scalar(select(func.count()).select_from(HostObservation)) == 0
        # Runs without remaining references are pruned; event-referenced runs survive.
        assert s.scalar(select(func.count()).select_from(Run)) == 1


def test_retention_respects_time_budget(env, ingest_run):
    hosts = [(f"192.0.2.{i}", f"02:00:00:00:00:0{i}", []) for i in range(1, 4)]
    ingest_run(xml(hosts))
    removed = cleanup(env[0], env[1], 1000 + 31 * 86400, batch=1, budget_seconds=0)
    assert removed["host_observations"] == 1


def test_worker_lease_fences_stale_result(env):
    with transaction(env[0]) as s:
        first = acquire(s, "a", 1000)
        assert acquire(s, "b", 1001) is None
    with transaction(env[0]) as s:
        second = acquire(s, "b", 1021)
        assert second > first
        assert not fenced(s, "a", first, 1022)
        assert claim(s, "a", first, 1022) is None


@pytest.mark.parametrize(
    "value", ["--script=bad", "example.com", "::/0", "192.0.2.0/16", "0.0.0.0", "127.0.0.1"]
)
def test_scope_rejects_unsafe_targets(value):
    with pytest.raises(ValueError):
        scope(value)


@pytest.mark.parametrize("value", ["0", "65536", "22;whoami", "1-2-3", "-p80", "90-80"])
def test_ports_reject_invalid_values(value):
    with pytest.raises(ValueError):
        ports(value)


def test_parser_rejects_entities_and_truncation():
    from xml.etree.ElementTree import ParseError

    from defusedxml.common import EntitiesForbidden

    with pytest.raises(EntitiesForbidden):
        parse_xml(
            b'<!DOCTYPE x [<!ENTITY test SYSTEM "file:///etc/passwd">]><nmaprun>&test;</nmaprun>'
        )
    with pytest.raises(ParseError):
        parse_xml(b"<nmaprun><host>")


def test_history_search_matches_port_and_version_evidence(browser, env, ingest_run):
    ingest_run(xml())
    ingest_run(
        xml(
            [
                (
                    "192.0.2.1",
                    None,
                    [
                        (
                            8080,
                            "open",
                            {"name": "http", "method": "probed", "version": "fixture-version-42"},
                        )
                    ],
                )
            ],
            coverage="8080",
            at=1120,
        ),
        kind="ports",
    )
    sign_in(browser)
    result = browser.get(
        "/api/v1/events", params={"category": "ports", "q": "fixture-version-42"}
    ).json()
    assert result["total"] == 1
    assert result["items"][0]["facts"]["port"] == 8080
    assert browser.get("/api/v1/events", params={"q": "unobserved-version"}).json()["total"] == 0
