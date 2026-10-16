import subprocess
from types import SimpleNamespace

import httpx
import pytest
from conftest import xml
from network_dragon.domain.ingest import ingest
from network_dragon.notifications.pushover import Pushover
from network_dragon.persistence.db import transaction
from network_dragon.persistence.models import Device, Network, Outbox, Run
from network_dragon.scanner import process
from network_dragon.worker.dispatcher import dispatch_one
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.mark.parametrize("same_mac", [True, False])
def test_conflicting_identities_are_withheld(env, ingest_run, same_mac):
    hosts = [
        ("192.0.2.1", "02:00:00:00:00:01", []),
        (
            "192.0.2.2" if same_mac else "192.0.2.1",
            "02:00:00:00:00:01" if same_mac else "02:00:00:00:00:02",
            [],
        ),
    ]
    run_id = ingest_run(xml(hosts))
    with Session(env[0]) as s:
        assert s.get(Run, run_id).status == "partial"
        assert not list(s.scalars(select(Device)))
        assert s.get(Run, run_id).coverage["identity_conflicts"]


def test_fixture_never_contacts_real_provider_even_when_enabled(env, ingest_run, monkeypatch):
    ingest_run(xml())
    with transaction(env[0]) as s:
        s.get(Network, env[2]).baseline = False
    ingest_run(xml([("192.0.2.2", "02:00:00:00:00:02", [])], at=1120))

    def forbidden(_):
        raise AssertionError("Real fixture delivery must never occur")

    provider = Pushover(httpx.Client(transport=httpx.MockTransport(forbidden)))
    monkeypatch.setenv("PUSHOVER_TOKEN", "test-only")
    monkeypatch.setenv("PUSHOVER_USER", "test-only")
    dispatch_one(env[0], env[1], provider, 1121)
    with Session(env[0]) as s:
        assert not list(s.scalars(select(Outbox).where(Outbox.status == "pending")))


@pytest.mark.parametrize(
    "code, body, expected",
    [
        (200, {"status": 1}, "accepted"),
        (429, {}, "rate_limited"),
        (503, {}, "provider_unavailable"),
        (200, {"status": 0}, "provider_rejected"),
    ],
)
def test_provider_outcomes(code, body, expected, monkeypatch):
    monkeypatch.setenv("PUSHOVER_TOKEN", "test-only")
    monkeypatch.setenv("PUSHOVER_USER", "test-only")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(code, json=body, headers={"retry-after": "123"})
        )
    )
    result = Pushover(client).send("presence test")
    assert result.outcome == expected
    if code == 429:
        assert result.retry_after == 123


def test_out_of_scope_fixture_rejected_atomically(env):
    with pytest.raises(ValueError, match="out-of-scope"):
        with transaction(env[0]) as session:
            ingest(
                session,
                network_id=env[2],
                data=xml([("198.51.100.1", None, [])]),
                kind="discovery",
                config=env[1],
            )
    with Session(env[0]) as session:
        assert not list(session.scalars(select(Run)))


def test_fake_nmap_process_never_opens_socket(env, monkeypatch):
    config = env[1]
    config.live_scanning, config.allowed_cidrs, config.allowed_interfaces = (
        True,
        ["192.0.2.0/29"],
        ["fixture0"],
    )
    network = SimpleNamespace(mode="live", enabled=True, cidr="192.0.2.0/29", interface="fixture0")
    profile = SimpleNamespace(kind="discovery", budget=60)
    calls = []

    class FakeProcess:
        returncode = 0

        def __init__(self, args, **kwargs):
            calls.append((args, kwargs["shell"], kwargs["start_new_session"]))
            kwargs["stdout"].write(xml())

        def poll(self):
            return 0

    monkeypatch.setattr(process, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(process, "interface_health", lambda n: None)
    monkeypatch.setattr(process, "route_health", lambda n, t: None)
    monkeypatch.setattr(process.subprocess, "Popen", FakeProcess)
    data, args = process.execute(config, network, profile, network.cidr)
    assert data == xml()
    assert calls[0][1:] == (False, True)
    assert args[-1] == "192.0.2.0/29"


def test_route_validation_requires_on_link_interface(monkeypatch):
    monkeypatch.setattr(process.psutil, "net_if_addrs", lambda: {})
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout=b'[{"dev":"wrong0","gateway":"192.0.2.1"}]'),
    )
    with pytest.raises(ValueError, match="configured on-link"):
        process.route_health(SimpleNamespace(interface="lab0"), "192.0.2.2")
