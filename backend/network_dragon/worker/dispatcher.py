import random
from datetime import UTC, datetime

from sqlalchemy import select

from network_dragon.domain.policy import delivery_type_allowed
from network_dragon.persistence.db import transaction
from network_dragon.persistence.models import (
    DeliveryAttempt,
    Device,
    Event,
    Network,
    Outbox,
    Setting,
)


def dispatch_one(engine, config, provider, now):
    if not config.notifications:
        return False
    with transaction(engine) as session:
        pause = session.get(Setting, "delivery_paused")
        if pause and pause.value.get("paused"):
            return False
        entry = session.scalar(
            select(Outbox)
            .where(Outbox.status.in_(["pending", "sending"]), Outbox.next_attempt <= now)
            .order_by(Outbox.next_attempt)
            .limit(1)
        )
        if not entry:
            return False
        event = session.get(Event, entry.event_id)
        device = session.get(Device, event.device_id) if event.device_id else None
        network = session.get(Network, event.network_id)
        reason = None
        if not delivery_type_allowed(event.type):
            reason = "ineligible event type"
        elif getattr(provider, "real", False) and network.mode != "live":
            reason = "Fixture evidence cannot trigger real delivery"
        elif network.baseline or not network.enabled:
            reason = "scope inactive or baseline review"
        elif not device or device.archived or not device.monitored or device.canonical_id:
            reason = "device no longer monitored"
        elif device.mute_until and device.mute_until > now:
            reason = "muted"
        elif event.type != "device.new" and not device.watched:
            reason = "device is not watched"
        elif event.type == "presence.offline" and (
            device.presence != "offline" or device.episode != event.episode
        ):
            reason = "outage superseded"
        elif event.type == "presence.recovered":
            accepted = session.scalar(
                select(Outbox.id)
                .join(Event, Event.id == Outbox.event_id)
                .where(
                    Event.episode == event.episode,
                    Event.type == "presence.offline",
                    Outbox.status == "accepted",
                )
            )
            if not accepted or device.presence != "online":
                reason = "recovery superseded or outage not accepted"
        if (
            not reason
            and device is not None
            and event.type != "presence.recovered"
            and device.last_notified
            and now - device.last_notified < config.cooldown_seconds
        ):
            reason = "device cooldown"
        if reason:
            entry.status, entry.reason = "suppressed", reason
            return True
        assert device is not None
        entry.status, entry.next_attempt = "sending", now + 30
        entry.attempts += 1
        entry_id = entry.id
        label = device.name or device.hostname or device.ip
        when = datetime.fromtimestamp(event.at, UTC).isoformat(timespec="seconds")
        message = f"{label} ({device.ip}): {event.type.removeprefix('presence.').replace('device.', '')}. Observed {when}."
    # Deliberately outside the database transaction; ambiguous acceptance is at-least-once.
    result = provider.send(message)
    with transaction(engine) as session:
        entry = session.get(Outbox, entry_id)
        session.add(DeliveryAttempt(outbox_id=entry.id, at=now, outcome=result.outcome))
        if result.outcome == "accepted":
            entry.status, entry.accepted_at, entry.reason = "accepted", now, ""
            event = session.get(Event, entry.event_id)
            device = session.get(Device, event.device_id)
            device.last_notified = now
        elif result.outcome in {"provider_rejected", "credentials_missing"} or entry.attempts >= 8:
            entry.status, entry.reason = "failed", result.outcome
        else:
            entry.status, entry.reason = "pending", result.outcome
            entry.next_attempt = now + max(
                result.retry_after, min(3600, 30 * 2**entry.attempts) + random.uniform(0, 10)
            )
    return True


def dispatch_test(engine, config, provider, now):
    """An explicit, fixed-message test request is separate from domain events."""
    if not config.notifications:
        return False
    from network_dragon.persistence.models import Audit

    with transaction(engine) as session:
        setting = session.get(Setting, "notification_test")
        if not setting or setting.value.get("status") != "queued":
            return False
        value = dict(setting.value)
        setting.value = {**value, "status": "sending", "at": now}
    result = provider.send(
        "Network Dragon test notification. Presence notifications are configured. Service changes remain history-only."
    )
    with transaction(engine) as session:
        setting = session.get(Setting, "notification_test")
        setting.value = {**value, "status": result.outcome, "at": now}
        session.add(
            Audit(
                action="notification.test_result",
                subject=value["id"],
                facts={"outcome": result.outcome},
            )
        )
    return True
