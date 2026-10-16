import time
import uuid

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Network(Base):
    __tablename__ = "networks"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    cidr: Mapped[str]
    interface: Mapped[str] = mapped_column(default="")
    mode: Mapped[str] = mapped_column(default="fixture")
    enabled: Mapped[bool] = mapped_column(default=True)
    baseline: Mapped[bool] = mapped_column(default=True)
    last_discovery: Mapped[float | None]
    health: Mapped[str] = mapped_column(default="unknown")
    health_reason: Mapped[str] = mapped_column(default="No discovery evidence yet")
    last_guard_ack: Mapped[float | None]


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("network_id", "identity"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), index=True)
    identity: Mapped[str]
    mac: Mapped[str | None]
    confidence: Mapped[str] = mapped_column(default="provisional")
    ip: Mapped[str]
    hostname: Mapped[str] = mapped_column(default="")
    name: Mapped[str] = mapped_column(default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    acknowledged: Mapped[bool] = mapped_column(default=False)
    watched: Mapped[bool] = mapped_column(default=False)
    archived: Mapped[bool] = mapped_column(default=False)
    monitored: Mapped[bool] = mapped_column(default=True)
    canonical_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"))
    presence: Mapped[str] = mapped_column(default="unknown", index=True)
    first_seen: Mapped[float]
    last_seen: Mapped[float]
    last_evidence: Mapped[float]
    misses: Mapped[int] = mapped_column(default=0)
    mute_until: Mapped[float | None]
    episode: Mapped[str | None]
    last_notified: Mapped[float | None]


class Address(Base):
    __tablename__ = "device_addresses"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    address: Mapped[str]
    family: Mapped[int] = mapped_column(default=4)
    first_seen: Mapped[float]
    last_seen: Mapped[float]
    ended_at: Mapped[float | None]


class Profile(Base):
    __tablename__ = "scan_profiles"
    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    kind: Mapped[str]
    revision: Mapped[int] = mapped_column(default=1)
    ports: Mapped[str] = mapped_column(default="top1000")
    budget: Mapped[int] = mapped_column(default=60)
    enrichment: Mapped[bool] = mapped_column(default=False)


class Job(Base):
    __tablename__ = "scan_jobs"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(unique=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"))
    profile_id: Mapped[str] = mapped_column(ForeignKey("scan_profiles.id"))
    target: Mapped[str]
    status: Mapped[str] = mapped_column(default="queued", index=True)
    created_at: Mapped[float] = mapped_column(default=time.time)
    started_at: Mapped[float | None]
    finished_at: Mapped[float | None]
    owner: Mapped[str | None]
    generation: Mapped[int] = mapped_column(default=0)
    lease_until: Mapped[float | None]
    attempts: Mapped[int] = mapped_column(default=0)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str] = mapped_column(default="")


class Run(Base):
    __tablename__ = "scan_runs"
    id: Mapped[str] = mapped_column(primary_key=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("scan_jobs.id"))
    kind: Mapped[str]
    source: Mapped[str]
    observed_at: Mapped[float] = mapped_column(index=True)
    status: Mapped[str]
    health_reason: Mapped[str] = mapped_column(default="")
    coverage: Mapped[dict] = mapped_column(JSON)
    checksum: Mapped[str]
    version: Mapped[str]
    profile_revision: Mapped[str]
    arguments: Mapped[list] = mapped_column(JSON, default=list)


class HostObservation(Base):
    __tablename__ = "host_observations"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    observed_at: Mapped[float] = mapped_column(index=True)
    facts: Mapped[dict] = mapped_column(JSON)


class PortObservation(Base):
    __tablename__ = "port_observations"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    observed_at: Mapped[float] = mapped_column(index=True)
    port: Mapped[int]
    protocol: Mapped[str] = mapped_column(default="tcp")
    facts: Mapped[dict] = mapped_column(JSON)


class CurrentPort(Base):
    __tablename__ = "current_ports"
    __table_args__ = (UniqueConstraint("device_id", "protocol", "port"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"))
    observed_at: Mapped[float]
    port: Mapped[int]
    protocol: Mapped[str] = mapped_column(default="tcp")
    state: Mapped[str]
    facts: Mapped[dict] = mapped_column(JSON)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(unique=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), index=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("scan_runs.id"))
    type: Mapped[str] = mapped_column(index=True)
    at: Mapped[float] = mapped_column(index=True)
    baseline: Mapped[bool] = mapped_column(default=False)
    facts: Mapped[dict] = mapped_column(JSON)
    episode: Mapped[str | None]


class Outbox(Base):
    __tablename__ = "notification_outbox"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), unique=True)
    status: Mapped[str] = mapped_column(default="pending", index=True)
    reason: Mapped[str] = mapped_column(default="")
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt: Mapped[float] = mapped_column(index=True)
    accepted_at: Mapped[float | None]


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    outbox_id: Mapped[str] = mapped_column(ForeignKey("notification_outbox.id"), index=True)
    at: Mapped[float] = mapped_column(index=True)
    outcome: Mapped[str]


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    password_hash: Mapped[str]


class AuthSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(primary_key=True)
    csrf: Mapped[str]
    expires: Mapped[float]


class LoginLimit(Base):
    __tablename__ = "login_limits"
    key: Mapped[str] = mapped_column(primary_key=True)
    count: Mapped[int]
    expires: Mapped[float]


class Audit(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    at: Mapped[float] = mapped_column(default=time.time)
    action: Mapped[str]
    subject: Mapped[str]
    facts: Mapped[dict] = mapped_column(JSON, default=dict)


class WorkerLease(Base):
    __tablename__ = "worker_lease"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    owner: Mapped[str]
    generation: Mapped[int]
    expires: Mapped[float]
    heartbeat: Mapped[float]


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
