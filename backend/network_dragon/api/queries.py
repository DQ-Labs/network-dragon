"""Read queries shared by the JSON API and the MCP endpoint."""

import time

from sqlalchemy import Text, func, or_, select

from network_dragon.persistence.models import (
    Address,
    CurrentPort,
    Device,
    Event,
    Job,
    Network,
    Run,
    Setting,
)

PRESENCE = ["online", "offline", "suspected_missing", "unknown"]
CATEGORIES = {
    "presence": ["presence.%", "device.%"],
    "ports": ["port.%", "service.%"],
    "identity": ["identity.%"],
    "system": ["scanner.%"],
}


def record(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def page(session, stmt, offset, limit):
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    return {
        "items": [record(row) for row in session.scalars(stmt.offset(offset).limit(limit))],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def device_query(q="", presence="", sort="ip"):
    stmt = select(Device).where(Device.canonical_id.is_(None))
    if q:
        stmt = stmt.where(
            or_(
                *(
                    column.icontains(q[:120], autoescape=True)
                    for column in (Device.name, Device.hostname, Device.ip, Device.mac)
                )
            )
        )
    if presence:
        stmt = stmt.where(Device.presence == presence)
    return stmt.order_by(
        {"name": Device.name, "ip": Device.ip, "last_seen": Device.last_seen.desc()}[sort],
        Device.id,
    )


def enrich_devices(session, config, items):
    if not items:
        return items
    health = dict(
        session.execute(
            select(Network.id, Network.health).where(
                Network.id.in_({item["network_id"] for item in items})
            )
        ).all()
    )
    open_ports = dict(
        session.execute(
            select(CurrentPort.device_id, func.count())
            .where(
                CurrentPort.device_id.in_([item["id"] for item in items]),
                CurrentPort.state == "open",
            )
            .group_by(CurrentPort.device_id)
        ).all()
    )
    now = time.time()
    for item in items:
        item["stale"] = (
            now - item["last_evidence"] > config.discovery_seconds * 3
            or health.get(item["network_id"]) != "healthy"
        )
        item["open_ports"] = open_ports.get(item["id"], 0)
    return items


def device_detail(session, config, device):
    result = enrich_devices(session, config, [record(device)])[0]
    result["addresses"] = [
        record(a)
        for a in session.scalars(
            select(Address)
            .where(Address.device_id == device.id)
            .order_by(Address.first_seen.desc())
        )
    ]
    result["aliases"] = [
        record(d) for d in session.scalars(select(Device).where(Device.canonical_id == device.id))
    ]
    return result


def event_query(category="", device_id="", q="", since=None):
    stmt = select(Event)
    if device_id:
        stmt = stmt.where(Event.device_id == device_id)
    if category in CATEGORIES:
        stmt = stmt.where(or_(*(Event.type.like(pattern) for pattern in CATEGORIES[category])))
    if q:
        stmt = stmt.where(
            or_(
                Event.type.contains(q[:120], autoescape=True),
                Event.facts.cast(Text).contains(q[:120], autoescape=True),
            )
        )
    if since is not None:
        stmt = stmt.where(Event.at >= since)
    return stmt.order_by(Event.at.desc(), Event.id)


def device_counts(session):
    devices = list(
        session.scalars(
            select(Device).where(Device.archived.is_(False), Device.canonical_id.is_(None))
        )
    )
    counts = {
        state: sum(d.presence == state and d.monitored for d in devices) for state in PRESENCE
    }
    counts.update(
        total=len(devices),
        awaiting_review=sum(not d.acknowledged for d in devices),
        watched=sum(d.watched for d in devices),
        unmonitored=sum(not d.monitored for d in devices),
    )
    return counts


def delivery_paused(session):
    pause = session.get(Setting, "delivery_paused")
    return bool(pause and pause.value.get("paused"))


def jobs_query():
    return select(Job).order_by(Job.created_at.desc())


def runs_query():
    return select(Run).order_by(Run.observed_at.desc())
