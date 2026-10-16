import pytest
from conftest import xml
from fastapi.testclient import TestClient
from network_dragon.api.app import create_app
from network_dragon.auth.service import set_password
from network_dragon.operations.backup import backup, restore
from network_dragon.operations.retention import cleanup
from network_dragon.persistence.db import engine_for, transaction
from network_dragon.persistence.models import Device, Event, Setting
from network_dragon.scanner.validation import ports, scope
from network_dragon.scanner.xml import parse_xml
from network_dragon.worker.queue import acquire, claim, fenced
from sqlalchemy import select
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


def test_retention_preserves_event_evidence(env, ingest_run):
    ingest_run(xml())
    cleanup(env[0], env[1], 1000 + 31 * 86400)
    with Session(env[0]) as s:
        e = s.scalar(select(Event).where(Event.type == "device.new"))
        assert e.facts["ip"] == "192.0.2.1"
        assert e.run_id


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
