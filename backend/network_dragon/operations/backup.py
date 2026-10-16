import hashlib
import json
import sqlite3
import time
from pathlib import Path

from sqlalchemy import delete

from network_dragon import __version__
from network_dragon.persistence.db import engine_for, transaction
from network_dragon.persistence.models import AuthSession, Outbox, Setting


def backup(config):
    directory = Path(config.backup_directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"dragon-{time.time_ns()}.db"
    with sqlite3.connect(config.database) as source, sqlite3.connect(destination) as target:
        source.backup(target, pages=256)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed")
        schema = target.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    manifest = {
        "application": __version__,
        "schema": schema,
        "created_at": time.time(),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "config": config.model_dump(),
        "secrets": "Excluded; back up separately",
    }
    destination.with_suffix(".json").write_text(json.dumps(manifest, indent=2))
    engine = engine_for(config.database)
    with transaction(engine) as session:
        setting = session.get(Setting, "last_backup")
        if setting:
            setting.value = {"at": manifest["created_at"], "checksum": manifest["sha256"]}
        else:
            session.add(
                Setting(
                    key="last_backup",
                    value={"at": manifest["created_at"], "checksum": manifest["sha256"]},
                )
            )
    engine.dispose()
    for old in sorted(directory.glob("dragon-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)[
        7:
    ]:
        old.unlink()
        old.with_suffix(".json").unlink(missing_ok=True)
    return destination


def restore(source: Path, destination: Path):
    if destination.exists():
        raise ValueError(
            "Restore requires a new destination; stop services and preserve the existing database"
        )
    manifest = json.loads(source.with_suffix(".json").read_text())
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("Backup checksum mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True) as src,
        sqlite3.connect(destination) as dst,
    ):
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Restored database integrity check failed")
    engine = engine_for(str(destination))
    with transaction(engine) as session:
        setting = session.get(Setting, "delivery_paused")
        if setting:
            setting.value = {"paused": True}
        else:
            session.add(Setting(key="delivery_paused", value={"paused": True}))
        session.execute(delete(AuthSession))
        session.execute(delete(Setting).where(Setting.key == "notification_test"))
        from sqlalchemy import select

        from network_dragon.persistence.models import Job, WorkerLease

        for entry in session.scalars(
            select(Outbox).where(Outbox.status.in_(["pending", "sending"]))
        ):
            entry.status, entry.reason = (
                "suppressed",
                "Restored backup: old messages require reconciliation, never replayed",
            )
        for job in session.scalars(select(Job).where(Job.status.in_(["running", "queued"]))):
            job.status, job.error = "expired", "Restored backup"
        session.execute(delete(WorkerLease))
    engine.dispose()
