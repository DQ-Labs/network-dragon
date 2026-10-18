import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from network_dragon.api.agent import agent_server
from network_dragon.api.queries import (
    delivery_paused,
    device_counts,
    device_detail,
    device_query,
    enrich_devices,
    event_query,
    jobs_query,
    page,
    record,
    runs_query,
)
from network_dragon.auth.service import (
    COOKIE,
    authenticate,
    login,
    set_password,
    token_refusal,
    verify,
)
from network_dragon.config import Config, load_config, secret
from network_dragon.persistence.db import engine_for, transaction
from network_dragon.persistence.models import (
    Audit,
    CurrentPort,
    DeliveryAttempt,
    Device,
    Event,
    HostObservation,
    Job,
    Network,
    Outbox,
    PortObservation,
    Profile,
    Run,
    Setting,
    User,
    WorkerLease,
)
from network_dragon.scanner.validation import ports, scope, validate_live
from network_dragon.worker.queue import enqueue


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(Input):
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(Input):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class DevicePatch(Input):
    name: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=4000)
    acknowledged: bool | None = None
    watched: bool | None = None
    archived: bool | None = None
    mute_until: float | None = Field(default=None, ge=0)


class NetworkCreate(Input):
    name: str = Field(min_length=1, max_length=120)
    cidr: str
    interface: str = Field(default="", max_length=32)
    mode: Literal["fixture", "live"] = "fixture"


class NetworkPatch(Input):
    enabled: bool | None = None
    activate_notifications: bool = False
    acknowledge_guard: bool = False


class ScanRequest(Input):
    network_id: str
    profile_id: str = "discovery"
    target: str


class MergeRequest(Input):
    canonical_id: str
    reason: str = Field(min_length=5, max_length=500)


class ProfileCreate(Input):
    name: str = Field(min_length=1, max_length=120)
    ports: str = Field(max_length=65536)
    budget: int = Field(default=60, ge=10, le=900)
    enrichment: bool = False


class DeliveryPause(Input):
    paused: bool


def create_app(config: Config | None = None, engine=None):
    config = config or load_config()
    engine = engine or engine_for(config.database)
    agent, agent_app = agent_server(engine, config)

    @asynccontextmanager
    async def lifespan(_):
        async with agent.session_manager.run():
            yield

    app = FastAPI(
        title="Network Dragon",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.engine, app.state.config = engine, config

    @app.middleware("http")
    async def security(request, call_next):
        # /mcp is POST-only JSON-RPC; any browser Origin other than ours is refused on every method.
        if request.method not in {"GET", "HEAD", "OPTIONS"} or request.url.path == "/mcp":
            origin = request.headers.get("origin")
            expected = urlsplit(str(request.base_url))
            if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (
                expected.scheme,
                expected.netloc,
            ):
                return JSONResponse({"detail": "Cross-origin mutation rejected"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site mutation rejected"}, status_code=403)
        if refusal := token_refusal(request):
            return JSONResponse({"detail": refusal}, status_code=403)
        if config.allow_http_local and request.url.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "testserver",
        }:
            return JSONResponse(
                {"detail": "Development HTTP is restricted to localhost"}, status_code=403
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api/") or request.url.path == "/mcp":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def db():
        with Session(engine) as session:
            yield session

    def admin(request: Request, session=Depends(db)):
        return authenticate(session, request)

    protected = [Depends(admin)]

    def get(session, model, id_):
        value = session.get(model, id_)
        if not value:
            raise HTTPException(404, "Record not found")
        return value

    app.add_route("/mcp", agent_app, include_in_schema=False)

    @app.get("/api/v1/openapi.json", dependencies=protected, include_in_schema=False)
    def openapi_schema():
        return app.openapi()

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready(session=Depends(db)):
        try:
            if not session.get(User, 1):
                return JSONResponse({"status": "not_ready"}, status_code=503)
            return {"status": "ready"}
        except Exception:
            return JSONResponse({"status": "not_ready"}, status_code=503)

    @app.post("/api/v1/session")
    def sign_in(payload: Credentials, request: Request, response: Response):
        with transaction(engine) as session:
            result, error = login(session, request, payload.password)
        if error:
            raise HTTPException(
                429 if error == "rate_limited" else 401,
                "Try again later" if error == "rate_limited" else "Invalid credentials",
            )
        token, csrf = result
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            secure=not config.allow_http_local,
            samesite="strict",
            max_age=43200,
            path="/",
        )
        return {"csrf": csrf}

    @app.get("/api/v1/session")
    def current(auth=Depends(admin)):
        return {"csrf": auth.csrf}

    @app.delete("/api/v1/session", dependencies=protected)
    def logout(response: Response, auth=Depends(admin)):
        with transaction(engine) as session:
            session.delete(session.get(type(auth), auth.token_hash))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.put("/api/v1/session/password", dependencies=protected)
    def password(payload: PasswordChange, response: Response):
        with transaction(engine) as session:
            if not verify(session, payload.current_password):
                raise HTTPException(403, "Current password is incorrect")
            set_password(session, payload.new_password)
            session.add(Audit(action="password.changed", subject="administrator"))
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/v1/overview", dependencies=protected)
    def overview(session=Depends(db)):
        return {
            "counts": device_counts(session),
            "networks": [record(n) for n in session.scalars(select(Network))],
            "worker": record(session.get(WorkerLease, 1)) if session.get(WorkerLease, 1) else None,
            "presence": page(
                session,
                select(Event)
                .where(
                    Event.type.in_(
                        [
                            "device.new",
                            "presence.online",
                            "presence.offline",
                            "presence.recovered",
                            "presence.suspected_missing",
                        ]
                    )
                )
                .order_by(Event.at.desc()),
                0,
                6,
            )["items"],
            "ports": page(
                session,
                select(Event)
                .where(Event.type.in_(["port.state", "service.changed"]))
                .order_by(Event.at.desc()),
                0,
                6,
            )["items"],
            "discovery_seconds": config.discovery_seconds,
            "ports_seconds": config.ports_seconds,
        }

    @app.get("/api/v1/devices", dependencies=protected)
    def devices(
        q: str = "",
        presence: str = "",
        sort: Literal["name", "last_seen", "ip"] = "ip",
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        session=Depends(db),
    ):
        data = page(session, device_query(q, presence, sort), offset, limit)
        data["items"] = enrich_devices(session, config, data["items"])
        return data

    @app.get("/api/v1/devices/{id_}", dependencies=protected)
    def device(id_: str, session=Depends(db)):
        return device_detail(session, config, get(session, Device, id_))

    @app.patch("/api/v1/devices/{id_}", dependencies=protected)
    def edit_device(id_: str, payload: DevicePatch):
        with transaction(engine) as session:
            device = get(session, Device, id_)
            changes = payload.model_dump(exclude_unset=True)
            for key, value in changes.items():
                if value is None and key != "mute_until":
                    raise ValueError("Only mute_until may be null")
                setattr(device, key, value)
            network = session.get(Network, device.network_id)
            device.monitored = network.enabled and not device.archived and not device.canonical_id
            session.add(Audit(action="device.updated", subject=id_, facts=changes))
        return {"ok": True}

    @app.post("/api/v1/devices/{id_}/merge", dependencies=protected)
    def merge(id_: str, payload: MergeRequest):
        with transaction(engine) as session:
            source, canonical = (
                get(session, Device, id_),
                get(session, Device, payload.canonical_id),
            )
            if (
                source.id == canonical.id
                or source.network_id != canonical.network_id
                or source.canonical_id
                or canonical.canonical_id
            ):
                raise ValueError(
                    "Merge needs two separate, unmerged identities in the same network"
                )
            aliases = session.scalar(select(Device.id).where(Device.canonical_id == source.id))
            if aliases:
                raise ValueError("Merge aliases individually; chained mappings are unsupported")
            source.canonical_id, source.monitored = canonical.id, False
            session.add(Audit(action="identity.merged", subject=id_, facts=payload.model_dump()))
        return {"ok": True}

    @app.get("/api/v1/devices/{id_}/ports", dependencies=protected)
    def device_ports(
        id_: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
        session=Depends(db),
    ):
        get(session, Device, id_)
        return page(
            session,
            select(CurrentPort).where(CurrentPort.device_id == id_).order_by(CurrentPort.port),
            offset,
            limit,
        )

    @app.get("/api/v1/devices/{id_}/observations", dependencies=protected)
    def observations(
        id_: str,
        kind: Literal["host", "port"] = "host",
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        session=Depends(db),
    ):
        model = HostObservation if kind == "host" else PortObservation
        return page(
            session,
            select(model).where(model.device_id == id_).order_by(model.observed_at.desc()),
            offset,
            limit,
        )

    @app.get("/api/v1/events", dependencies=protected)
    def events(
        category: str = "",
        device_id: str = "",
        q: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        session=Depends(db),
    ):
        return page(session, event_query(category, device_id, q), offset, limit)

    @app.get("/api/v1/scans", dependencies=protected)
    def scans(
        offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), session=Depends(db)
    ):
        return {
            "jobs": page(session, jobs_query(), offset, limit),
            "runs": page(session, runs_query(), offset, limit),
        }

    @app.get("/api/v1/scans/{id_}", dependencies=protected)
    def scan(id_: str, session=Depends(db)):
        run, job = session.get(Run, id_), session.get(Job, id_)
        if not run and not job:
            raise HTTPException(404, "Scan not found")
        return {"run": record(run) if run else None, "job": record(job) if job else None}

    @app.post("/api/v1/scans", dependencies=protected)
    def queue(payload: ScanRequest):
        with transaction(engine) as session:
            job = enqueue(
                session,
                config,
                get(session, Network, payload.network_id),
                get(session, Profile, payload.profile_id),
                payload.target,
            )
            return record(job)

    @app.post("/api/v1/scans/{id_}/cancel", dependencies=protected)
    def cancel(id_: str):
        with transaction(engine) as session:
            job = get(session, Job, id_)
            if job.status in {"queued", "running"}:
                job.cancel_requested = True
                session.add(Audit(action="scan.cancel_requested", subject=id_))
        return {"ok": True}

    @app.get("/api/v1/networks", dependencies=protected)
    def networks(session=Depends(db)):
        return [record(n) for n in session.scalars(select(Network))]

    @app.post("/api/v1/networks", dependencies=protected)
    def add_network(payload: NetworkCreate):
        scope(payload.cidr, config.max_targets)
        with transaction(engine) as session:
            network = Network(**payload.model_dump(), enabled=True)
            if network.mode == "live":
                validate_live(network.cidr, network, config)
            session.add(network)
            session.flush()
            session.add(
                Audit(action="network.created", subject=network.id, facts=payload.model_dump())
            )
            return record(network)

    @app.patch("/api/v1/networks/{id_}", dependencies=protected)
    def edit_network(id_: str, payload: NetworkPatch):
        with transaction(engine) as session:
            network = get(session, Network, id_)
            if payload.activate_notifications:
                if network.health != "healthy" or not network.last_discovery:
                    raise ValueError("Review a healthy discovery baseline first")
                network.baseline = False
            if payload.enabled is not None:
                network.enabled = payload.enabled
                if not network.enabled:
                    for job in session.scalars(
                        select(Job).where(
                            Job.network_id == id_, Job.status.in_(["queued", "running"])
                        )
                    ):
                        job.cancel_requested = True
                for device in session.scalars(select(Device).where(Device.network_id == id_)):
                    device.monitored = (
                        network.enabled and not device.archived and not device.canonical_id
                    )
                    device.misses = 0
            if payload.acknowledge_guard:
                network.last_guard_ack = time.time()
            session.add(
                Audit(
                    action="network.updated",
                    subject=id_,
                    facts=payload.model_dump(exclude_unset=True),
                )
            )
        return {"ok": True}

    @app.get("/api/v1/scan-profiles", dependencies=protected)
    def profiles(session=Depends(db)):
        return [record(p) for p in session.scalars(select(Profile))]

    @app.post("/api/v1/scan-profiles", dependencies=protected)
    def add_profile(payload: ProfileCreate):
        from network_dragon.persistence.models import uid

        ports(payload.ports)
        with transaction(engine) as session:
            profile = Profile(id=uid(), kind="ports", **payload.model_dump())
            session.add(profile)
            session.flush()
            session.add(
                Audit(action="profile.created", subject=profile.id, facts=payload.model_dump())
            )
            return record(profile)

    @app.get("/api/v1/notifications", dependencies=protected)
    def notifications(
        offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), session=Depends(db)
    ):
        result = page(session, select(Outbox).order_by(Outbox.next_attempt.desc()), offset, limit)
        items = result["items"]
        events = {
            e.id: record(e)
            for e in session.scalars(
                select(Event).where(Event.id.in_([i["event_id"] for i in items]))
            )
        }
        attempts: dict[str, list] = {i["id"]: [] for i in items}
        for attempt in session.scalars(
            select(DeliveryAttempt)
            .where(DeliveryAttempt.outbox_id.in_(attempts))
            .order_by(DeliveryAttempt.at, DeliveryAttempt.id)
        ):
            attempts[attempt.outbox_id].append(record(attempt))
        for item in items:
            item["event"], item["delivery_attempts"] = (
                events[item["event_id"]],
                attempts[item["id"]],
            )
        return result

    @app.post("/api/v1/notifications/pause", dependencies=protected)
    def pause(payload: DeliveryPause):
        with transaction(engine) as session:
            setting = session.get(Setting, "delivery_paused")
            if not setting:
                setting = Setting(key="delivery_paused", value={})
                session.add(setting)
            # Unpause never replays pending pre-pause messages.
            if payload.paused:
                for entry in session.scalars(select(Outbox).where(Outbox.status == "pending")):
                    entry.status, entry.reason = "suppressed", "Delivery paused by administrator"
            setting.value = {"paused": payload.paused}
            session.add(
                Audit(
                    action="delivery.pause_changed",
                    subject="installation",
                    facts=payload.model_dump(),
                )
            )
        return {"ok": True}

    @app.post("/api/v1/notifications/test", dependencies=protected)
    def notification_test():
        from network_dragon.persistence.models import uid

        if not config.notifications or not secret("PUSHOVER_TOKEN") or not secret("PUSHOVER_USER"):
            raise ValueError(
                "Explicit delivery configuration and server-side credentials are required"
            )
        with transaction(engine) as session:
            setting = session.get(Setting, "notification_test")
            if setting and setting.value.get("status") in {"queued", "sending"}:
                return setting.value
            if setting and time.time() - setting.value.get("at", 0) < 60:
                raise HTTPException(429, "Wait one minute before another test")
            value = {"id": uid(), "status": "queued", "at": time.time()}
            if setting:
                setting.value = value
            else:
                session.add(Setting(key="notification_test", value=value))
            session.add(Audit(action="notification.test_requested", subject=value["id"]))
            return value

    @app.get("/api/v1/settings", dependencies=protected)
    def settings(session=Depends(db)):
        test = session.get(Setting, "notification_test")
        last_backup = session.get(Setting, "last_backup")
        return {
            **config.model_dump(exclude={"nmap", "database", "frontend", "backup_directory"}),
            "credentials_configured": bool(secret("PUSHOVER_TOKEN") and secret("PUSHOVER_USER")),
            "delivery_paused": delivery_paused(session),
            "port_notifications": "never",
            "notification_test": test.value if test else None,
            "version": "0.1.0",
            "database_bytes": Path(config.database).stat().st_size
            if Path(config.database).exists()
            else 0,
            "last_backup": last_backup.value if last_backup else None,
        }

    @app.get("/{path:path}")
    def frontend(path: str):
        root = Path(config.frontend).resolve()
        file = (root / path).resolve()
        if path.startswith(("api/", "health/", "mcp/", ".well-known/")):
            raise HTTPException(404)
        if file.is_relative_to(root) and file.is_file():
            return FileResponse(file)
        if (root / "index.html").exists():
            return FileResponse(root / "index.html")
        return JSONResponse(
            {"detail": "Build the frontend with npm run build in frontend/"}, status_code=503
        )

    return app
