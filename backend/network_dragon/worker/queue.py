import hashlib
import time

from sqlalchemy import select

from network_dragon.persistence.models import (
    Audit,
    Device,
    Job,
    Network,
    Profile,
    Setting,
    WorkerLease,
)
from network_dragon.scanner.validation import validate_live


def seed_profiles(session, config=None):
    for id_, name, kind, ports, budget, enrich in [
        ("discovery", "Local ARP discovery", "discovery", "", 60, False),
        ("routine", "Top 1,000 TCP", "ports", "top1000", 60, False),
        ("full-tcp", "Full TCP · manual", "ports", "1-65535", 900, False),
        ("services", "Service enrichment · manual", "ports", "top1000", 180, True),
    ]:
        if not session.get(Profile, id_):
            session.add(
                Profile(id=id_, name=name, kind=kind, ports=ports, budget=budget, enrichment=enrich)
            )
    if config:
        profile_id = "routine"
        if config.routine_ports != "top1000" or config.routine_budget_seconds != 60:
            profile_id = (
                "routine-"
                + hashlib.sha256(
                    f"{config.routine_ports}:{config.routine_budget_seconds}".encode()
                ).hexdigest()[:12]
            )
            if not session.get(Profile, profile_id):
                session.add(
                    Profile(
                        id=profile_id,
                        name="Configured routine TCP",
                        kind="ports",
                        ports=config.routine_ports,
                        budget=config.routine_budget_seconds,
                    )
                )
        setting = session.get(Setting, "routine_profile")
        if setting:
            setting.value = {"id": profile_id}
        else:
            session.add(Setting(key="routine_profile", value={"id": profile_id}))


def enqueue(session, config, network, profile, target, key=None, now=None):
    now = time.time() if now is None else now
    validate_live(target, network, config)
    if profile.kind == "discovery" and target != network.cidr:
        raise ValueError("Discovery jobs must cover the complete configured network")
    if profile.kind == "ports":
        device = session.scalar(
            select(Device).where(
                Device.network_id == network.id,
                Device.ip == target,
                Device.presence == "online",
                Device.monitored.is_(True),
                Device.archived.is_(False),
                Device.canonical_id.is_(None),
            )
        )
        if not device or now - device.last_seen > config.discovery_seconds * 3:
            raise ValueError("Port scans require a recently discovered device")
    active = session.scalar(
        select(Job).where(
            Job.network_id == network.id,
            Job.profile_id == profile.id,
            Job.target == target,
            Job.status.in_(["queued", "running"]),
        )
    )
    if active:
        return active
    if key:
        prior = session.scalar(select(Job).where(Job.key == key))
        if prior:
            return prior
    job = Job(
        key=key or f"manual:{network.id}:{profile.id}:{target}:{now}",
        network_id=network.id,
        profile_id=profile.id,
        target=target,
        created_at=now,
    )
    session.add(job)
    session.flush()
    session.add(
        Audit(action="scan.queued", subject=job.id, facts={"target": target, "profile": profile.id})
    )
    return job


def schedule(session, config, now):
    if not config.live_scanning:
        return
    for network in session.scalars(
        select(Network).where(Network.enabled.is_(True), Network.mode == "live")
    ):
        discovery = session.get(Profile, "discovery")
        enqueue(
            session,
            config,
            network,
            discovery,
            network.cidr,
            f"schedule:{network.id}:discovery:{int(now // config.discovery_seconds)}",
            now,
        )
        for device in session.scalars(
            select(Device).where(
                Device.network_id == network.id,
                Device.presence == "online",
                Device.monitored.is_(True),
                Device.archived.is_(False),
                Device.canonical_id.is_(None),
            )
        ):
            if now - device.last_seen <= config.discovery_seconds * 3:
                enqueue(
                    session,
                    config,
                    network,
                    session.get(
                        Profile,
                        session.get(Setting, "routine_profile").value["id"]
                        if session.get(Setting, "routine_profile")
                        else "routine",
                    ),
                    device.ip,
                    f"schedule:{network.id}:{device.id}:routine:{int(now // config.ports_seconds)}",
                    now,
                )


def acquire(session, owner, now):
    lease = session.get(WorkerLease, 1)
    if lease and lease.owner != owner and lease.expires > now:
        return None
    if not lease:
        lease = WorkerLease(id=1, owner=owner, generation=1, expires=now + 20, heartbeat=now)
        session.add(lease)
    else:
        if lease.owner != owner or lease.expires <= now:
            lease.generation += 1
        lease.owner, lease.expires, lease.heartbeat = owner, now + 20, now
    return lease.generation


def fenced(session, owner, generation, now):
    lease = session.get(WorkerLease, 1)
    return bool(
        lease and lease.owner == owner and lease.generation == generation and lease.expires > now
    )


def claim(session, owner, generation, now):
    if not fenced(session, owner, generation, now):
        return None
    for old in session.scalars(select(Job).where(Job.status == "running", Job.lease_until <= now)):
        old.status, old.error, old.finished_at = (
            "expired",
            "Worker lease expired; no negative evidence applied",
            now,
        )
        from network_dragon.domain.ingest import reset_misses

        if session.get(Profile, old.profile_id).kind == "discovery":
            reset_misses(session, old.network_id)
    for queued in session.scalars(select(Job).where(Job.status == "queued")):
        if queued.cancel_requested:
            queued.status, queued.finished_at = "cancelled", now
        elif queued.key.startswith("schedule:") and now - queued.created_at > 180:
            queued.status, queued.finished_at = "expired", now
    session.flush()
    job = session.scalar(
        select(Job)
        .join(Profile, Profile.id == Job.profile_id)
        .where(Job.status == "queued")
        .order_by(Profile.kind.asc(), Job.created_at)
        .limit(1)
    )
    if not job:
        return None
    job.status, job.owner, job.generation = "running", owner, generation
    job.started_at, job.lease_until, job.attempts = now, now + 20, job.attempts + 1
    session.flush()
    return job.id
