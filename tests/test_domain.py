from pathlib import Path

import pytest
from conftest import xml
from network_dragon.domain.policy import delivery_type_allowed
from network_dragon.persistence.db import transaction
from network_dragon.persistence.models import (
    Address,
    CurrentPort,
    Device,
    Event,
    Network,
    Outbox,
    Run,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def device(engine):
    with Session(engine) as s:
        return s.scalar(select(Device))


def activate(env, watched=True):
    engine, _, network_id = env
    with transaction(engine) as s:
        s.get(Network, network_id).baseline = False
        for d in s.scalars(select(Device)):
            d.watched = watched


def test_baseline_idempotency(env, ingest_run):
    engine, _, _ = env
    ingest_run(xml(), run_id="same")
    ingest_run(xml(), run_id="same")
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Device)) == 1
        assert s.scalar(select(func.count()).select_from(Run)) == 1
        assert not list(s.scalars(select(Outbox).where(Outbox.status == "pending")))


def test_new_after_review_not_duplicated(env, ingest_run):
    ingest_run(xml())
    activate(env)
    hosts = [("192.0.2.1", "02:00:00:00:00:01", []), ("192.0.2.2", "02:00:00:00:00:02", [])]
    ingest_run(xml(hosts, at=1120))
    ingest_run(xml(hosts, at=1240))
    with Session(env[0]) as s:
        assert len(list(s.scalars(select(Outbox).where(Outbox.status == "pending")))) == 1


def test_dhcp_and_reused_address_preserve_identity(env, ingest_run):
    ingest_run(xml())
    first = device(env[0]).id
    ingest_run(xml([("192.0.2.2", "02:00:00:00:00:01", [])], at=1120))
    assert device(env[0]).id == first
    assert device(env[0]).ip == "192.0.2.2"
    ingest_run(xml([("192.0.2.2", "02:00:00:00:00:02", [])], at=1240))
    with Session(env[0]) as s:
        assert s.scalar(select(func.count()).select_from(Device)) == 2
        assert len(list(s.scalars(select(Address).where(Address.ended_at.is_(None))))) == 1


def test_missing_mac_is_provisional(env, ingest_run):
    ingest_run(xml([("192.0.2.1", None, [])]))
    assert device(env[0]).confidence == "provisional"


def test_vendor_refreshed_only_by_reported_value(env, ingest_run):
    ingest_run(xml([("192.0.2.1", "02:00:00:00:00:01", [], "Raspberry Pi Trading")]))
    assert device(env[0]).vendor == "Raspberry Pi Trading"
    ingest_run(xml(at=1120))
    assert device(env[0]).vendor == "Raspberry Pi Trading"
    ingest_run(xml([("192.0.2.1", "02:00:00:00:00:01", [], "Raspberry Pi (Trading) Ltd")], at=1240))
    assert device(env[0]).vendor == "Raspberry Pi (Trading) Ltd"


def test_vendor_migration_keeps_existing_devices(env, tmp_path):
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from network_dragon.persistence.db import engine_for, migrate

    engine = engine_for(str(tmp_path / "old.db"))
    config = AlembicConfig()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "backend/migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0002")
        connection.exec_driver_sql(
            "INSERT INTO networks VALUES ('n', 'n', '192.0.2.0/29', '', 'live', 1, 0, NULL, 'healthy', '', NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO devices (id, network_id, identity, confidence, ip, hostname, name, notes, acknowledged, watched, archived, monitored, presence, first_seen, last_seen, last_evidence, misses) VALUES ('d', 'n', 'ip:192.0.2.1', 'provisional', '192.0.2.1', '', '', '', 0, 0, 0, 1, 'online', 1, 1, 1, 0)"
        )
    migrate(engine)
    with Session(engine) as s:
        assert s.get(Device, "d").vendor is None
    engine.dispose()


def test_three_misses_and_duration_then_recovery(env, ingest_run):
    ingest_run(xml())
    activate(env)
    for at in [1120, 1240]:
        ingest_run(xml([], at=at))
        assert device(env[0]).presence == "suspected_missing"
    ingest_run(xml([], at=1360))
    assert device(env[0]).presence == "offline"
    ingest_run(xml([], at=1480))
    ingest_run(xml(at=1600))
    assert device(env[0]).presence == "online"
    with Session(env[0]) as s:
        assert len(list(s.scalars(select(Event).where(Event.type == "presence.offline")))) == 1
        assert len(list(s.scalars(select(Event).where(Event.type == "presence.recovered")))) == 1
        outage = s.scalar(select(Outbox).join(Event).where(Event.type == "presence.offline"))
        assert outage.status == "cancelled"
        recovery = s.scalar(select(Outbox).join(Event).where(Event.type == "presence.recovered"))
        assert recovery.status == "suppressed"


def test_three_fast_misses_not_sufficient(env, ingest_run):
    ingest_run(xml())
    for at in [1050, 1100, 1150]:
        ingest_run(xml([], at=at))
    assert device(env[0]).presence == "suspected_missing"


@pytest.mark.parametrize("bad", ["partial", "unhealthy", "coverage", "gap"])
def test_bad_evidence_breaks_miss_sequence(env, ingest_run, bad):
    ingest_run(xml())
    ingest_run(xml([], at=1120))
    ingest_run(xml([], at=1240))
    if bad == "partial":
        ingest_run(xml([], at=1360, complete=False))
    elif bad == "unhealthy":
        ingest_run(xml([], at=1360), healthy=False)
    elif bad == "coverage":
        ingest_run(xml([], at=1360, total=7))
    else:
        ingest_run(xml([], at=2000))
    ingest_run(xml([], at=2120 if bad == "gap" else 1480))
    assert device(env[0]).presence != "offline"
    assert device(env[0]).misses < 3


def test_mass_disappearance_does_not_offline(env, ingest_run):
    hosts = [(f"192.0.2.{i}", f"02:00:00:00:00:0{i}", []) for i in range(1, 5)]
    ingest_run(xml(hosts))
    activate(env)
    for at in [1120, 1240, 1360, 1480, 1600]:
        ingest_run(xml([], at=at))
    with Session(env[0]) as s:
        assert all(d.presence == "online" and d.misses == 0 for d in s.scalars(select(Device)))
        assert s.get(Network, env[2]).health == "suspect"
        assert not list(s.scalars(select(Outbox).where(Outbox.status == "pending")))


def test_late_discovery_cannot_overwrite(env, ingest_run):
    ingest_run(xml(at=2000))
    ingest_run(xml([], at=1000))
    assert device(env[0]).last_seen == 2000
    assert device(env[0]).misses == 0


def test_ports_never_infer_presence(env, ingest_run):
    ingest_run(xml())
    for at in [1120, 1240, 1360]:
        ingest_run(xml([], at=at))
    ingest_run(
        xml([("192.0.2.1", None, [(80, "open", {})])], coverage="80", total=1, at=1500),
        kind="ports",
        targets="192.0.2.1",
    )
    assert device(env[0]).presence == "offline"


@pytest.mark.parametrize("state", ["closed", "filtered", "open|filtered", "open"])
def test_port_changes_are_logged_but_never_enqueued(env, ingest_run, state):
    ingest_run(xml())
    activate(env)
    engine = env[0]
    with transaction(engine) as s:
        for entry in s.scalars(select(Outbox)):
            s.delete(entry)
    for at, current in [(1100, "open" if state != "open" else "closed"), (1200, state)]:
        ingest_run(
            xml([("192.0.2.1", None, [(80, current, {})])], coverage="80", total=1, at=at),
            kind="ports",
        )
    with Session(engine) as s:
        assert s.scalar(select(CurrentPort)).state == state
        assert s.scalar(select(Event).where(Event.type == "port.state")) is not None
        assert not list(s.scalars(select(Outbox)))


@pytest.mark.parametrize("scenario", ["uncovered", "timeout", "ambiguous", "partial"])
def test_uncertain_port_evidence_never_closes(env, ingest_run, scenario):
    ingest_run(xml())
    ingest_run(xml([("192.0.2.1", None, [(80, "open", {})])], coverage="80", at=1100), kind="ports")
    kwargs = {"coverage": "80", "at": 1200}
    if scenario == "uncovered":
        kwargs["coverage"] = "443"
    if scenario == "timeout":
        kwargs["timeout"] = True
    if scenario == "partial":
        kwargs["complete"] = False
    if scenario == "ambiguous":
        kwargs["aggregates"] = (
            '<extraports count="1" state="closed"/><extraports count="1" state="filtered"/>'
        )
    ingest_run(xml([("192.0.2.1", None, [])], **kwargs), kind="ports")
    with Session(env[0]) as s:
        assert s.scalar(select(CurrentPort)).state == "open"


def test_unambiguous_aggregate_updates_only_existing_ports(env, ingest_run):
    ingest_run(xml())
    ingest_run(
        xml([("192.0.2.1", None, [(80, "open", {})])], coverage="1-65535", at=1100), kind="ports"
    )
    ingest_run(
        xml(
            [("192.0.2.1", None, [])],
            coverage="1-65535",
            at=1200,
            aggregates='<extraports count="65535" state="closed"/>',
        ),
        kind="ports",
    )
    with Session(env[0]) as s:
        assert s.scalar(select(CurrentPort)).state == "closed"
        assert s.scalar(select(func.count()).select_from(CurrentPort)) == 1


@pytest.mark.parametrize(
    "first_coverage, aggregates, expected",
    [
        ("22,80,443", '<extraports count="2" state="closed"/>', "port.state"),
        ("22,80", '<extraports count="1" state="closed"/>', "port.baseline"),
        ("22,80,443", "", "port.baseline"),
    ],
    ids=["aggregate-proved-closed", "newly-covered", "no-prior-aggregate"],
)
def test_newly_open_port_compares_prior_aggregate(
    env, ingest_run, first_coverage, aggregates, expected
):
    ingest_run(xml())
    ingest_run(
        xml(
            [("192.0.2.1", None, [(22, "open", {})])],
            coverage=first_coverage,
            at=1100,
            aggregates=aggregates,
        ),
        kind="ports",
    )
    ingest_run(
        xml(
            [("192.0.2.1", None, [(22, "open", {}), (443, "open", {})])],
            coverage="22,80,443",
            at=1200,
            aggregates='<extraports count="1" state="closed"/>',
        ),
        kind="ports",
    )
    with Session(env[0]) as s:
        events = list(s.scalars(select(Event).where(Event.type.like("port.%"), Event.at == 1200)))
        assert [(e.type, e.facts["port"]) for e in events] == [(expected, 443)]
        if expected == "port.state":
            assert not events[0].baseline
            assert events[0].facts["before"]["state"] == "closed"
            assert events[0].facts["after"]["state"] == "open"
        assert s.scalar(select(CurrentPort).where(CurrentPort.port == 443)).state == "open"
        assert not list(s.scalars(select(Outbox).join(Event).where(Event.type.like("port.%"))))


def test_enrichment_missing_evidence_and_service_change(env, ingest_run):
    ingest_run(xml())
    services = [
        dict(name="http", method="probed", product="Server", version="1"),
        dict(name="http", method="table"),
        dict(name="http", method="probed", product="Server", version="1"),
        dict(name="http", method="probed", product="Server", version="2"),
    ]
    for i, service in enumerate(services):
        ingest_run(
            xml([("192.0.2.1", None, [(80, "open", service)])], coverage="80", at=1100 + i * 100),
            kind="ports",
        )
    with Session(env[0]) as s:
        assert len(list(s.scalars(select(Event).where(Event.type == "service.changed")))) == 1
        assert not list(s.scalars(select(Outbox).join(Event).where(Event.type.like("service.%"))))


@pytest.mark.parametrize(
    "event",
    [
        "port.opened",
        "port.closed",
        "port.state",
        "port.digest",
        "service.changed",
        "service.version",
        "unknown",
        "scanner.health",
        "presence.online",
    ],
)
def test_policy_fails_closed(event):
    assert not delivery_type_allowed(event)


def test_reused_ip_ports_follow_current_binding(env, ingest_run):
    ingest_run(xml())
    ingest_run(xml([("192.0.2.1", "02:00:00:00:00:02", [])], at=1120))
    ingest_run(xml([("192.0.2.1", None, [(80, "open", {})])], coverage="80", at=1200), kind="ports")
    with Session(env[0]) as s:
        port = s.scalar(select(CurrentPort))
        assert port is not None
        assert s.get(Device, port.device_id).mac == "02:00:00:00:00:02"


def test_missing_version_keeps_original_evidence_time(env, ingest_run):
    ingest_run(xml())
    for at, service in [
        (1100, {"name": "http", "method": "probed", "version": "1"}),
        (1200, {"name": "http", "method": "probed"}),
    ]:
        ingest_run(
            xml([("192.0.2.1", None, [(80, "open", service)])], coverage="80", at=at), kind="ports"
        )
    with Session(env[0]) as s:
        facts = s.scalar(select(CurrentPort)).facts
        assert facts["version"] == "1"
        assert facts["service_seen"] == {"name": 1200, "version": 1100}
        assert facts["service_observed_at"] == 1100
