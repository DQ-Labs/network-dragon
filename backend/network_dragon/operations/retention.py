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


def cleanup(engine, config, now, batch=500):
    removed = {}
    with transaction(engine) as session:
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
        old = list(
            session.scalars(
                select(Outbox.id)
                .where(
                    Outbox.status.in_(["accepted", "suppressed", "failed", "cancelled"]),
                    Outbox.next_attempt < now - config.retention_delivery_days * 86400,
                    ~Outbox.id.in_(select(DeliveryAttempt.outbox_id)),
                    ~Outbox.event_id.in_(
                        select(Event.id).where(
                            Event.episode.in_(
                                select(Device.episode).where(Device.episode.is_not(None))
                            )
                        )
                    ),
                )
                .limit(batch)
            )
        )
        session.execute(delete(Outbox).where(Outbox.id.in_(old)))
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
        session.execute(delete(AuthSession).where(AuthSession.expires < now))
        session.execute(delete(LoginLimit).where(LoginLimit.expires < now))
    return removed
