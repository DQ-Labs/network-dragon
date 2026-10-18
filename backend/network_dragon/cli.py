import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy import select

from network_dragon.auth.service import set_password
from network_dragon.config import load_config
from network_dragon.domain.ingest import ingest
from network_dragon.persistence.db import engine_for, migrate, transaction
from network_dragon.persistence.models import Network, Profile
from network_dragon.scanner.validation import scope
from network_dragon.worker.queue import enqueue, seed_profiles


def main():
    parser = argparse.ArgumentParser(prog="network-dragon")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Apply migrations and seed fixed profiles; no scans")
    sub.add_parser("create-admin", help="Set the local administrator password interactively")
    web = sub.add_parser("web")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8000)
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    fixture = sub.add_parser("import-fixture")
    fixture.add_argument("path", type=Path)
    fixture.add_argument("--cidr", required=True)
    fixture.add_argument("--name", default="Fixture lab")
    fixture.add_argument("--kind", choices=["discovery", "ports"], default="discovery")
    live = sub.add_parser("queue-live", help="Queue an explicitly configured live scan")
    live.add_argument("--network", required=True)
    live.add_argument("--target", required=True)
    live.add_argument("--profile", default="discovery")
    sub.add_parser("backup")
    sub.add_parser("retention")
    restore_cmd = sub.add_parser("restore")
    restore_cmd.add_argument("source", type=Path)
    restore_cmd.add_argument("destination", type=Path)
    args = parser.parse_args()
    config = load_config()
    engine = engine_for(config.database)
    try:
        if args.command == "init":
            migrate(engine)
            with transaction(engine) as session:
                seed_profiles(session, config)
            print("Database initialized. Live scans and notifications remain configuration-gated.")
        elif args.command == "create-admin":
            password = getpass.getpass("Administrator password (12+ characters): ")
            if password != getpass.getpass("Confirm password: "):
                raise ValueError("Passwords do not match")
            with transaction(engine) as session:
                set_password(session, password)
            print("Administrator configured. Existing sessions invalidated.")
        elif args.command == "import-fixture":
            scope(args.cidr)
            with transaction(engine) as session:
                network = session.scalar(
                    select(Network).where(Network.cidr == args.cidr, Network.mode == "fixture")
                )
                if not network:
                    network = Network(name=args.name, cidr=args.cidr, mode="fixture")
                    session.add(network)
                    session.flush()
                run = ingest(
                    session,
                    network_id=network.id,
                    data=args.path.read_bytes(),
                    kind=args.kind,
                    config=config,
                )
                print(f"Fixture {run.id}: {run.status}. No network activity.")
        elif args.command == "queue-live":
            with transaction(engine) as session:
                network, profile = (
                    session.get(Network, args.network),
                    session.get(Profile, args.profile),
                )
                if not network or not profile:
                    raise ValueError("Unknown network/profile")
                job = enqueue(session, config, network, profile, args.target)
                print(f"Queued {job.id}")
        elif args.command == "web":
            import uvicorn

            from network_dragon.api.app import create_app

            uvicorn.run(
                create_app(config, engine),
                host=args.host,
                port=args.port,
                proxy_headers=bool(config.trusted_proxy_ips),
                forwarded_allow_ips=",".join(config.trusted_proxy_ips),
            )
        elif args.command == "worker":
            from network_dragon.worker.main import run_worker

            run_worker(engine, config, args.once)
        elif args.command == "backup":
            from network_dragon.operations.backup import backup

            print(backup(config))
        elif args.command == "restore":
            from network_dragon.operations.backup import restore

            restore(args.source, args.destination)
            print(
                "Restored with delivery paused, stale messages suppressed, and sessions invalidated."
            )
        elif args.command == "retention":
            import time

            from network_dragon.operations.retention import cleanup

            print(cleanup(engine, config, time.time(), budget_seconds=None))
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
