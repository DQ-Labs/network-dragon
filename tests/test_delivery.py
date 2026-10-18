from conftest import xml
from network_dragon.notifications.pushover import Delivery, FakePushover, Pushover
from network_dragon.persistence.db import transaction
from network_dragon.persistence.models import DeliveryAttempt, Device, Event, Network, Outbox
from network_dragon.worker.dispatcher import dispatch_one
from sqlalchemy import select
from sqlalchemy.orm import Session


def outage(env, ingest_run):
    ingest_run(xml())
    with transaction(env[0]) as s:
        s.get(Network, env[2]).baseline = False
        s.scalar(select(Device)).watched = True
    for at in [1120, 1240, 1360]:
        ingest_run(xml([], at=at))


def test_accepted_outage_paired_recovery(env, ingest_run):
    outage(env, ingest_run)
    provider = FakePushover()
    dispatch_one(env[0], env[1], provider, 1361)
    ingest_run(xml(at=1480))
    dispatch_one(env[0], env[1], provider, 1481)
    assert len(provider.messages) == 2
    assert "offline" in provider.messages[0] and "recovered" in provider.messages[1]
    assert "port" not in "".join(provider.messages).lower()


def test_transient_retry_then_recovery_cancels_outage(env, ingest_run):
    outage(env, ingest_run)
    provider = FakePushover([Delivery("provider_unavailable"), Delivery("accepted")])
    dispatch_one(env[0], env[1], provider, 1361)
    ingest_run(xml(at=1480))
    dispatch_one(env[0], env[1], provider, 2000)
    assert len(provider.messages) == 1
    with Session(env[0]) as s:
        assert not list(s.scalars(select(Outbox).where(Outbox.status == "pending")))


def test_dispatcher_rejects_forged_port_outbox(env, ingest_run):
    ingest_run(xml())
    with transaction(env[0]) as s:
        s.get(Network, env[2]).baseline = False
        d = s.scalar(select(Device))
        e = Event(
            key="forged", device_id=d.id, network_id=env[2], type="port.digest", at=1100, facts={}
        )
        s.add(e)
        s.flush()
        s.add(Outbox(event_id=e.id, next_attempt=1100))
    provider = FakePushover()
    dispatch_one(env[0], env[1], provider, 1101)
    assert not provider.messages


def test_mute_at_delivery_no_replay(env, ingest_run):
    outage(env, ingest_run)
    with transaction(env[0]) as s:
        s.scalar(select(Device)).mute_until = 2000
    provider = FakePushover()
    dispatch_one(env[0], env[1], provider, 1361)
    dispatch_one(env[0], env[1], provider, 3000)
    assert not provider.messages


def test_invalid_credentials_stop_retry(env, ingest_run):
    outage(env, ingest_run)
    provider = FakePushover([Delivery("provider_rejected")])
    dispatch_one(env[0], env[1], provider, 1361)
    dispatch_one(env[0], env[1], provider, 5000)
    assert len(provider.messages) == 1


def test_unexpected_provider_error_retries_then_fails(env, ingest_run):
    class Broken:
        def send(self, message):
            raise RuntimeError("unexpected provider bug with secret test-token")

    outage(env, ingest_run)
    for attempt in range(8):
        assert dispatch_one(env[0], env[1], Broken(), 1361 + attempt * 4000)
    with Session(env[0]) as s:
        entry = s.scalar(select(Outbox).where(Outbox.status != "suppressed"))
        assert (entry.status, entry.reason, entry.attempts) == ("failed", "provider_error", 8)
        outcomes = {a.outcome for a in s.scalars(select(DeliveryAttempt))}
        assert outcomes == {"provider_error"}
    assert not dispatch_one(env[0], env[1], Broken(), 50000)


def test_http_provider_sanitizes_response(monkeypatch):
    import httpx

    monkeypatch.setenv("PUSHOVER_TOKEN", "test-token")
    monkeypatch.setenv("PUSHOVER_USER", "test-user")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(400, json={"errors": ["secret test-token"]})
    )
    result = Pushover(httpx.Client(transport=transport)).send("Presence only")
    assert result.outcome == "provider_rejected"
    assert "test-token" not in repr(result)
