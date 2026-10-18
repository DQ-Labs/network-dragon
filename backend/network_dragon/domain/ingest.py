import hashlib
import ipaddress
from collections import Counter
from dataclasses import asdict

from sqlalchemy import select

from network_dragon.domain.policy import delivery_type_allowed, suppression
from network_dragon.persistence.models import (
    Address,
    CurrentPort,
    Device,
    Event,
    HostObservation,
    Network,
    Outbox,
    PortObservation,
    Run,
    Setting,
    uid,
)
from network_dragon.scanner.validation import excluded
from network_dragon.scanner.xml import Port, parse_xml


def emit(session, network, device, run, kind, at, facts, config, suffix="", baseline=False):
    event = Event(
        key=f"{run.id}:{device.id if device else network.id}:{kind}:{suffix}",
        device_id=device.id if device else None,
        network_id=network.id,
        run_id=run.id,
        type=kind,
        at=at,
        baseline=baseline,
        facts=facts,
        episode=device.episode if device else None,
    )
    session.add(event)
    session.flush()
    if not delivery_type_allowed(kind):
        return event
    accepted = False
    if device.episode:
        accepted = (
            session.scalar(
                select(Outbox.id)
                .join(Event, Event.id == Outbox.event_id)
                .where(
                    Event.episode == device.episode,
                    Event.type == "presence.offline",
                    Outbox.status == "accepted",
                )
            )
            is not None
        )
    paused = session.get(Setting, "delivery_paused")
    reason = suppression(
        kind,
        baseline=baseline or network.baseline,
        active=config.notifications and not (paused and paused.value.get("paused")),
        watched=device.watched,
        muted=bool(device.mute_until and device.mute_until > at),
        cooldown=bool(device.last_notified and at - device.last_notified < config.cooldown_seconds),
        outage_accepted=accepted,
    )
    session.add(
        Outbox(
            event_id=event.id,
            status="suppressed" if reason else "pending",
            reason=reason or "",
            next_attempt=at,
        )
    )
    return event


def reset_misses(session, network_id):
    for device in session.scalars(select(Device).where(Device.network_id == network_id)):
        device.misses = 0


def ingest(
    session,
    *,
    network_id,
    data,
    kind,
    config,
    targets=None,
    run_id=None,
    observed_at=None,
    healthy=True,
    health_reason="",
    source="fixture",
    profile_revision="fixture:1",
    job_id=None,
    arguments=None,
):
    network = session.get(Network, network_id)
    if not network:
        raise ValueError("Unknown monitored network")
    checksum = hashlib.sha256(data).hexdigest()
    run_id = run_id or hashlib.sha256(f"{network_id}:{kind}:{checksum}".encode()).hexdigest()
    existing = session.get(Run, run_id)
    if existing:
        return existing
    scan = parse_xml(data)
    at = observed_at if observed_at is not None else scan.observed_at
    target_scope = ipaddress.IPv4Network(targets or network.cidr)
    if not target_scope.subnet_of(ipaddress.IPv4Network(network.cidr)):
        raise ValueError("Result coverage exceeds monitored scope")
    if any(ipaddress.ip_address(h.ip) not in target_scope for h in scan.hosts):
        raise ValueError("Result contains an out-of-scope address")
    if kind not in {"discovery", "ports"}:
        raise ValueError("Unknown scan kind")
    # Excluded addresses (e.g. a honeypot) are never recorded, whoever produced the XML.
    skipped = excluded(config, target_scope)
    scan.hosts = [host for host in scan.hosts if host.ip not in skipped]
    trustworthy = healthy and scan.complete
    # Several MACs for one address is always ambiguous. One MAC on several addresses
    # is also a conflict (it may be a spoofed MAC) unless the operator listed it in
    # multihomed_macs; then it is one device bound to each address below.
    ip_counts = Counter(host.ip for host in scan.hosts if host.up)
    mac_counts = Counter(host.mac for host in scan.hosts if host.up and host.mac)
    shared = {mac for mac, count in mac_counts.items() if count > 1}
    unexpected = shared - set(config.multihomed_macs)
    conflicts = {host.ip for host in scan.hosts if ip_counts[host.ip] > 1 or host.mac in unexpected}
    if conflicts:
        trustworthy = False
        health_reason = (
            "One MAC answered for several addresses; list it in multihomed_macs if expected. "
            if unexpected
            else ""
        ) + "Conflicting IP/MAC evidence; ambiguous identities withheld for review"
    mac_addresses: dict[str, list[str]] = {}
    for host in scan.hosts:
        if host.up and host.complete and host.mac in shared and host.ip not in conflicts:
            mac_addresses.setdefault(host.mac, []).append(host.ip)
    full = target_scope.num_addresses
    if kind == "discovery" and scan.total not in {full, full - len(skipped)}:
        trustworthy = False
        health_reason = "Discovery did not cover the complete requested scope"
    run = Run(
        id=run_id,
        network_id=network_id,
        job_id=job_id,
        kind=kind,
        source=source,
        observed_at=at,
        status="succeeded" if trustworthy else "partial",
        health_reason=health_reason,
        coverage={
            "targets": str(target_scope),
            "ports": sorted(scan.coverage),
            "identity_conflicts": sorted(conflicts),
        },
        checksum=checksum,
        version=scan.version,
        profile_revision=profile_revision,
        arguments=arguments or [],
    )
    session.add(run)
    session.flush()
    devices = list(session.scalars(select(Device).where(Device.network_id == network_id)))
    # A late result remains evidence, but cannot rewrite newer projections.
    if kind == "discovery" and network.last_discovery and at <= network.last_discovery:
        run.status, run.health_reason = "expired", "Older than the latest discovery evidence"
        return run
    seen_ips = {host.ip for host in scan.hosts if host.up and host.complete}
    prior = [
        d
        for d in devices
        if d.presence in {"online", "suspected_missing"}
        and d.monitored
        and not d.archived
        and ipaddress.ip_address(d.ip) in target_scope
        and d.ip not in skipped
    ]
    missing = [d for d in prior if d.ip not in seen_ips]
    if kind == "discovery" and len(prior) >= 3 and len(missing) / len(prior) >= 0.8:
        trustworthy = False
        run.status, run.health_reason = (
            "suspect",
            "Mass disappearance guard: at least 80% of three or more devices missing",
        )
    if kind == "discovery":
        previous_health = network.health
        network.health = "healthy" if trustworthy else "suspect"
        network.health_reason = run.health_reason or (
            "Complete fixture evidence"
            if source == "fixture"
            else "Interface and coverage checks passed"
        )
        if previous_health != network.health:
            emit(
                session,
                network,
                None,
                run,
                "scanner.health",
                at,
                {"state": network.health, "reason": network.health_reason},
                config,
            )
        if network.last_discovery and at - network.last_discovery > config.discovery_seconds * 2.5:
            reset_misses(session, network_id)
        network.last_discovery = at
        if not trustworthy:
            reset_misses(session, network_id)
    observed_ids = set()
    for host in scan.hosts:
        if not host.up or not host.complete or host.ip in conflicts:
            continue
        identity = f"mac:{host.mac}" if host.mac else f"ip:{host.ip}"
        device = session.scalar(
            select(Device).where(Device.network_id == network_id, Device.identity == identity)
        )
        group = mac_addresses.get(host.mac, []) if kind == "discovery" and host.mac else []
        if len(group) > 1:
            # Keep the current primary address so a multi-homed device never flaps.
            primary = (
                device.ip
                if device and device.ip in group
                else min(group, key=ipaddress.IPv4Address)
            )
            if host.ip != primary:
                continue
        bound = set(group) if len(group) > 1 else {host.ip}
        if kind == "ports":
            # -Pn and service responses are never discovery/identity evidence.
            candidates = list(
                session.scalars(
                    select(Device)
                    .where(
                        Device.network_id == network_id,
                        Device.ip == host.ip,
                        Device.monitored.is_(True),
                        Device.canonical_id.is_(None),
                    )
                    .join(Address, Address.device_id == Device.id)
                    .where(Address.address == host.ip, Address.ended_at.is_(None))
                )
            )
            device = candidates[0] if len(candidates) == 1 else None
            if device is None or (host.mac and device.mac and host.mac != device.mac):
                continue
        elif device is None:
            device = Device(
                network_id=network_id,
                identity=identity,
                mac=host.mac,
                vendor=host.vendor or None,
                confidence="mac" if host.mac else "provisional",
                ip=host.ip,
                hostname=host.hostname,
                first_seen=at,
                last_seen=at,
                last_evidence=at,
            )
            session.add(device)
            session.flush()
            emit(
                session,
                network,
                device,
                run,
                "device.new",
                at,
                {"ip": host.ip, "mac": host.mac},
                config,
                baseline=network.baseline,
            )
        if device.canonical_id:
            # Keep original evidence, but avoid inventing a merged presence policy.
            session.add(
                HostObservation(
                    run_id=run.id, device_id=device.id, observed_at=at, facts=asdict(host)
                )
            )
            continue
        if kind == "discovery":
            if at < device.last_evidence:
                continue
            old_state = device.presence
            if device.ip != host.ip:
                emit(
                    session,
                    network,
                    device,
                    run,
                    "identity.address",
                    at,
                    {"before": device.ip, "after": host.ip},
                    config,
                )
            if host.hostname and device.hostname != host.hostname:
                emit(
                    session,
                    network,
                    device,
                    run,
                    "identity.hostname",
                    at,
                    {"before": device.hostname, "after": host.hostname},
                    config,
                )
                device.hostname = host.hostname
            # The OUI vendor is a label, not identity evidence; keep the last one reported.
            if host.vendor:
                device.vendor = host.vendor
            # Close conflicting and replaced bindings, without merging identities.
            for binding in session.scalars(
                select(Address)
                .join(Device, Address.device_id == Device.id)
                .where(Device.network_id == network_id, Address.ended_at.is_(None))
            ):
                if (binding.device_id == device.id and binding.address not in bound) or (
                    binding.address in bound and binding.device_id != device.id
                ):
                    binding.ended_at = at
            for address in sorted(bound, key=ipaddress.IPv4Address):
                binding = session.scalar(
                    select(Address).where(
                        Address.device_id == device.id,
                        Address.address == address,
                        Address.ended_at.is_(None),
                    )
                )
                if binding:
                    binding.last_seen = at
                    continue
                session.add(
                    Address(device_id=device.id, address=address, first_seen=at, last_seen=at)
                )
                if address != host.ip:
                    # History-only, like other identity events: a listed MAC gained an address.
                    emit(
                        session,
                        network,
                        device,
                        run,
                        "identity.address_added",
                        at,
                        {"address": address, "primary": host.ip, "mac": host.mac},
                        config,
                        address,
                    )
            device.ip, device.last_seen, device.last_evidence = host.ip, at, at
            device.monitored = network.enabled and not device.archived
            device.presence, device.misses = "online", 0
            observed_ids.add(device.id)
            if old_state == "offline":
                for pending in session.scalars(
                    select(Outbox)
                    .join(Event, Event.id == Outbox.event_id)
                    .where(
                        Event.episode == device.episode,
                        Event.type == "presence.offline",
                        Outbox.status.in_(["pending", "sending"]),
                    )
                ):
                    pending.status, pending.reason = "cancelled", "Device recovered before delivery"
                emit(
                    session,
                    network,
                    device,
                    run,
                    "presence.recovered",
                    at,
                    {"before": old_state, "after": "online"},
                    config,
                )
                device.episode = None
            elif old_state != "online":
                emit(
                    session,
                    network,
                    device,
                    run,
                    "presence.online",
                    at,
                    {"before": old_state, "after": "online"},
                    config,
                    baseline=network.baseline,
                )
        session.add(
            HostObservation(
                run_id=run.id,
                device_id=device.id,
                observed_at=at,
                facts={"ip": host.ip, "mac": host.mac, "up": host.up, "kind": kind}
                | (
                    {"addresses": sorted(bound, key=ipaddress.IPv4Address)}
                    if len(bound) > 1
                    else {}
                ),
            )
        )
        if kind == "ports" and trustworthy:
            apply_ports(session, network, device, run, host, scan.coverage, at, config)
    if kind == "discovery" and trustworthy:
        for device in devices:
            if (
                device.id in observed_ids
                or not device.monitored
                or device.archived
                or device.canonical_id
                or ipaddress.ip_address(device.ip) not in target_scope
                or device.ip in skipped
            ):
                continue
            if at <= device.last_evidence:
                continue
            device.last_evidence = at
            device.misses += 1
            if device.presence == "offline":
                continue
            before = device.presence
            if (
                device.misses >= config.offline_misses
                and at - device.last_seen >= config.offline_seconds
            ):
                device.presence, device.episode = "offline", uid()
                emit(
                    session,
                    network,
                    device,
                    run,
                    "presence.offline",
                    at,
                    {"before": before, "after": "offline", "misses": device.misses},
                    config,
                )
            else:
                device.presence = "suspected_missing"
                if before != device.presence:
                    emit(
                        session,
                        network,
                        device,
                        run,
                        "presence.suspected_missing",
                        at,
                        {"before": before, "after": device.presence},
                        config,
                    )
    return run


def prior_aggregate(session, device, run, at):
    """Ports an earlier unambiguous aggregate proved to be in one state, without materializing them."""
    observation = session.scalar(
        select(PortObservation)
        .where(
            PortObservation.device_id == device.id,
            PortObservation.port == 0,
            PortObservation.run_id != run.id,
            PortObservation.observed_at < at,
        )
        .order_by(PortObservation.observed_at.desc())
        .limit(1)
    )
    source = session.get(Run, observation.facts["coverage_run"]) if observation else None
    if not observation or not source:
        return "", set()
    omitted = set(source.coverage.get("ports", [])) - set(observation.facts.get("explicit", []))
    return observation.facts["aggregate"], omitted


def apply_ports(session, network, device, run, host, coverage, at, config):
    current = {
        p.port: p
        for p in session.scalars(select(CurrentPort).where(CurrentPort.device_id == device.id))
    }
    explicit = {p.port: p for p in host.ports}
    if host.aggregate_state:
        # Compact aggregate evidence lives on the host observation. Only materialize
        # omitted ports that have a projection to compare; never 65k closed rows.
        session.add(
            PortObservation(
                run_id=run.id,
                device_id=device.id,
                observed_at=at,
                port=0,
                facts={
                    "aggregate": host.aggregate_state,
                    "coverage_run": run.id,
                    "explicit": sorted(explicit),
                },
            )
        )
        for number in current.keys() & coverage - explicit.keys():
            explicit[number] = Port(number, host.aggregate_state, "aggregate")
    aggregate: tuple[str, set[int]] | None = None
    for port in explicit.values():
        facts = port.facts()
        session.add(
            PortObservation(
                run_id=run.id,
                device_id=device.id,
                observed_at=at,
                port=port.port,
                facts=port.facts(),
            )
        )
        service_seen = {
            key: at
            for key in ("name", "product", "version")
            if port.method == "probed" and facts[key]
        }
        if service_seen:
            facts["service_seen"] = service_seen
            facts["service_observed_at"] = at
        previous = current.get(port.port)
        if previous and at <= previous.observed_at:
            continue
        if previous is None:
            if aggregate is None:
                aggregate = prior_aggregate(session, device, run, at)
            state, omitted = aggregate
            before = Port(port.port, state, "aggregate").facts() if port.port in omitted else None
            session.add(
                CurrentPort(
                    device_id=device.id,
                    run_id=run.id,
                    observed_at=at,
                    port=port.port,
                    state=port.state,
                    facts=facts,
                )
            )
            if before and before["state"] != port.state:
                # Previously covered and proven by an aggregate: a real change, not a baseline.
                emit(
                    session,
                    network,
                    device,
                    run,
                    "port.state",
                    at,
                    {"port": port.port, "before": before, "after": facts},
                    config,
                    str(port.port),
                )
                continue
            emit(
                session,
                network,
                device,
                run,
                "port.baseline",
                at,
                {"port": port.port, "after": facts},
                config,
                str(port.port),
                baseline=True,
            )
            continue
        if previous.state != port.state:
            emit(
                session,
                network,
                device,
                run,
                "port.state",
                at,
                {"port": port.port, "before": previous.facts, "after": facts},
                config,
                str(port.port),
            )
        old = previous.facts
        if port.method == "probed" and old.get("method") == "probed":
            changes = {
                k: {"before": old.get(k), "after": facts[k]}
                for k in ("name", "product", "version")
                if facts[k]
                and old.get(k)
                and facts[k].strip().casefold() != old[k].strip().casefold()
            }
            if changes:
                emit(
                    session,
                    network,
                    device,
                    run,
                    "service.changed",
                    at,
                    {"port": port.port, "changes": changes},
                    config,
                    str(port.port),
                )
        # Missing evidence never erases a previously probed identity.
        if old.get("method") == "probed":
            prior_seen = old.get(
                "service_seen",
                {
                    key: old.get("service_observed_at", previous.observed_at)
                    for key in ("name", "product", "version")
                    if old.get(key)
                },
            )
            for key in ("name", "product", "version", "method", "confidence"):
                if port.method != "probed" or not facts[key]:
                    facts[key] = old.get(key, "")
                    if key in prior_seen:
                        service_seen[key] = prior_seen[key]
            facts["service_seen"] = service_seen
            if service_seen:
                facts["service_observed_at"] = min(service_seen.values())
        previous.facts, previous.state = facts, port.state
        previous.run_id, previous.observed_at = run.id, at
