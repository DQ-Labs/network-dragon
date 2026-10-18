import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from sqlalchemy import delete

from network_dragon import __version__
from network_dragon.persistence.db import engine_for, transaction
from network_dragon.persistence.models import AuthSession, Outbox, Setting


def copy(source, destination, failure, pages=-1):
    """Copy and verify a database, closing both connections; a failed copy is removed."""
    # sqlite3's own context manager only ends the transaction; it never closes.
    try:
        with closing(source), closing(sqlite3.connect(destination)) as target:
            source.backup(target, pages=pages)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError(failure)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def backup(config):
    directory = Path(config.backup_directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"dragon-{time.time_ns()}.db"
    copy(sqlite3.connect(config.database), destination, "Backup integrity check failed", 256)
    with closing(sqlite3.connect(destination)) as target:
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
    manifest_path = source.with_suffix(".json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(
            f"Cannot read backup manifest {manifest_path}; keep the matching .json beside the .db"
        ) from exc
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Backup manifest {manifest_path} must contain valid UTF-8 JSON") from exc
    checksum = manifest.get("sha256") if isinstance(manifest, dict) else None
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
        raise ValueError(f"Backup manifest {manifest_path} requires a valid SHA-256 checksum")
    try:
        actual_checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(f"Cannot read backup database {source}") from exc
    if actual_checksum != checksum.lower():
        raise ValueError("Backup checksum mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    copy(
        sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True),
        destination,
        "Restored database integrity check failed",
    )
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
