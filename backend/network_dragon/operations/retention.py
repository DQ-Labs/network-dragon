import time

from sqlalchemy import delete, select

from network_dragon.persistence.db import transaction
from network_dragon.persistence.models import (
    AuthSession,
    CurrentPort,
    DeliveryAttempt,
    Device,
    Event,
    HostObservation,
    LoginLimit,
    Outbox,
    PortObservation,
    Run,
)


def cleanup(engine, config, now, batch=500, budget_seconds: float | None = 10):
    """Drain expired rows in short, bounded transactions until caught up or out of time."""
    deadline = None if budget_seconds is None else time.monotonic() + budget_seconds
    removed: dict[str, int] = {}
    while True:
        with transaction(engine) as session:
            counts = prune(session, config, now, batch)
        for table, count in counts.items():
            removed[table] = removed.get(table, 0) + count
        # A partial batch everywhere means nothing eligible remains.
        if max(counts.values()) < batch or (deadline and time.monotonic() >= deadline):
            return removed


def prune(session, config, now, batch):
    removed = {}
    for model in (HostObservation, PortObservation):
        ids = list(
            session.scalars(
                select(model.id)
                .where(model.observed_at < now - config.retention_observations_days * 86400)
                .limit(batch)
            )
        )
        session.execute(delete(model).where(model.id.in_(ids)))
        removed[model.__tablename__] = len(ids)
    ids = list(
        session.scalars(
            select(DeliveryAttempt.id)
            .where(DeliveryAttempt.at < now - config.retention_delivery_days * 86400)
            .limit(batch)
        )
    )
    session.execute(delete(DeliveryAttempt).where(DeliveryAttempt.id.in_(ids)))
    removed[DeliveryAttempt.__tablename__] = len(ids)
    old = list(
        session.scalars(
            select(Outbox.id)
            .where(
                Outbox.status.in_(["accepted", "suppressed", "failed", "cancelled"]),
                Outbox.next_attempt < now - config.retention_delivery_days * 86400,
                ~Outbox.id.in_(select(DeliveryAttempt.outbox_id)),
                ~Outbox.event_id.in_(
                    select(Event.id).where(
                        Event.episode.in_(select(Device.episode).where(Device.episode.is_not(None)))
                    )
                ),
            )
            .limit(batch)
        )
    )
    session.execute(delete(Outbox).where(Outbox.id.in_(old)))
    removed[Outbox.__tablename__] = len(old)
    ids = list(
        session.scalars(
            select(Event.id)
            .where(
                Event.at < now - config.retention_events_days * 86400,
                ~Event.id.in_(select(Outbox.event_id)),
            )
            .limit(batch)
        )
    )
    session.execute(delete(Event).where(Event.id.in_(ids)))
    removed[Event.__tablename__] = len(ids)
    # Retain scans referenced by current state/events, even after detail expires.
    ids = list(
        session.scalars(
            select(Run.id)
            .where(
                Run.observed_at < now - config.retention_observations_days * 86400,
                ~Run.id.in_(select(Event.run_id).where(Event.run_id.is_not(None))),
                ~Run.id.in_(select(CurrentPort.run_id)),
                ~Run.id.in_(select(HostObservation.run_id)),
                ~Run.id.in_(select(PortObservation.run_id)),
            )
            .limit(batch)
        )
    )
    session.execute(delete(Run).where(Run.id.in_(ids)))
    removed[Run.__tablename__] = len(ids)
    session.execute(delete(AuthSession).where(AuthSession.expires < now))
    session.execute(delete(LoginLimit).where(LoginLimit.expires < now))
    return removed
