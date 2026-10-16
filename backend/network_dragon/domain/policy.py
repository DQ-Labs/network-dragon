"""The sole domain allowlist. Unknown/port/service event types always fail closed."""

PRESENCE_DELIVERY_TYPES = frozenset({"device.new", "presence.offline", "presence.recovered"})


def delivery_type_allowed(event_type: str) -> bool:
    return event_type in PRESENCE_DELIVERY_TYPES


def suppression(event_type, *, baseline, active, watched, muted, cooldown, outage_accepted):
    if not delivery_type_allowed(event_type):
        return "ineligible event type"
    if baseline or not active:
        return "baseline review / notifications inactive"
    if muted:
        return "muted"
    if event_type != "device.new" and not watched:
        return "device is not watched"
    if event_type == "presence.recovered" and not outage_accepted:
        return "outage was not delivered"
    if cooldown and event_type != "presence.recovered":
        return "device cooldown"
    return None
