from types import SimpleNamespace

import pytest
from conftest import xml
from network_dragon.notifications.pushover import FakePushover
from network_dragon.persistence.db import transaction
from network_dragon.persistence.models import Device, Job, Network, Profile, Setting
from network_dragon.scanner.process import arguments, interface_health
from network_dragon.worker.dispatcher import dispatch_test
from network_dragon.worker.queue import acquire, claim, enqueue, schedule
from sqlalchemy import select
from sqlalchemy.orm import Session


def configured(env):
    engine, config, network_id = env
    config.live_scanning = True
    config.allowed_cidrs = ["192.0.2.0/29"]
    config.allowed_interfaces = ["lab0"]
    with transaction(engine) as session:
        network = session.get(Network, network_id)
        network.mode, network.interface = "live", "lab0"
    return config


def test_schedule_idempotent_and_discovery_priority(env, ingest_run):
    ingest_run(xml())
    config = configured(env)
    with transaction(env[0]) as s:
        schedule(s, config, 1001)
        schedule(s, config, 1002)
        assert len(list(s.scalars(select(Job)))) == 2
        generation = acquire(s, "worker", 1002)
        id_ = claim(s, "worker", generation, 1002)
        assert s.get(Job, id_).profile_id == "discovery"
        assert claim(s, "other-worker", generation, 1003) is None


def test_crashed_job_expires_and_breaks_miss_sequence(env, ingest_run):
    ingest_run(xml())
    ingest_run(xml([], at=1120))
    config = configured(env)
    with transaction(env[0]) as s:
        schedule(s, config, 1121)
        generation = acquire(s, "old", 1121)
        old = claim(s, "old", generation, 1121)
    with transaction(env[0]) as s:
        generation = acquire(s, "new", 1200)
        claim(s, "new", generation, 1200)
        assert s.get(Job, old).status == "expired"
        assert s.scalar(select(Device)).misses == 0


def test_manual_queue_coalesces_and_port_evidence_must_be_recent(env, ingest_run):
    ingest_run(xml())
    config = configured(env)
    with transaction(env[0]) as s:
        network, profile = s.get(Network, env[2]), s.get(Profile, "routine")
        first = enqueue(s, config, network, profile, "192.0.2.1", now=1001)
        second = enqueue(s, config, network, profile, "192.0.2.1", now=1002)
        assert first.id == second.id
        with pytest.raises(ValueError):
            enqueue(s, config, network, profile, "192.0.2.1", now=5000)


def test_fixed_arguments_and_execution_revalidation(env):
    config = configured(env)
    with Session(env[0]) as s:
        network, profile = s.get(Network, env[2]), s.get(Profile, "routine")
        args = arguments(config, network, profile, "192.0.2.1")
        assert "-sT" in args and "-Pn" in args and "-A" not in args
        assert "--script" not in args and args[-1] == "192.0.2.1"
        config.allowed_cidrs = []
        with pytest.raises(ValueError):
            arguments(config, network, profile, "192.0.2.1")


def test_excluded_address_is_never_scanned(env, ingest_run):
    ingest_run(
        xml([("192.0.2.1", "02:00:00:00:00:01", []), ("192.0.2.3", "02:00:00:00:00:03", [])])
    )
    config = configured(env)
    config.excluded_addresses = ["192.0.2.3"]
    with transaction(env[0]) as s:
        network = s.get(Network, env[2])
        discovery, routine = s.get(Profile, "discovery"), s.get(Profile, "routine")
        args = arguments(config, network, discovery, "192.0.2.0/29")
        assert args[args.index("--exclude") + 1] == "192.0.2.3"
        with pytest.raises(ValueError, match="excluded"):
            arguments(config, network, routine, "192.0.2.3")
        with pytest.raises(ValueError, match="excluded"):
            enqueue(s, config, network, routine, "192.0.2.3", now=1001)
        schedule(s, config, 1001)
        assert {j.target for j in s.scalars(select(Job))} == {"192.0.2.0/29", "192.0.2.1"}


def test_missing_interface_fails_closed(monkeypatch):
    monkeypatch.setattr("psutil.net_if_stats", lambda: {})
    with pytest.raises(ValueError, match="missing or down"):
        interface_health(SimpleNamespace(interface="absent", cidr="192.0.2.0/29"))


def test_explicit_test_is_fixed_message_and_not_automatic(env):
    provider = FakePushover()
    assert not dispatch_test(env[0], env[1], provider, 1000)
    with transaction(env[0]) as s:
        s.add(
            Setting(
                key="notification_test",
                value={"id": "explicit-request", "status": "queued", "at": 1000},
            )
        )
    assert dispatch_test(env[0], env[1], provider, 1001)
    assert not dispatch_test(env[0], env[1], provider, 1002)
    assert len(provider.messages) == 1
