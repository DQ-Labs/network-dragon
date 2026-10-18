import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

from network_dragon.domain.ingest import ingest, reset_misses
from network_dragon.notifications.pushover import Pushover
from network_dragon.persistence.db import transaction
from network_dragon.persistence.models import Job, Network, Profile, uid
from network_dragon.scanner.process import execute
from network_dragon.worker.dispatcher import dispatch_one, dispatch_test
from network_dragon.worker.queue import acquire, claim, fenced, schedule, seed_profiles


def run_worker(engine, config, once=False):
    owner, current, future = uid(), None, None
    cancel = threading.Event()
    provider = Pushover()
    maintenance_at = time.time() + 3600
    with transaction(engine) as session:
        seed_profiles(session, config)
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            while True:
                now = time.time()
                with transaction(engine) as session:
                    generation = acquire(session, owner, now)
                    if generation is None:
                        cancel.set()
                        raise RuntimeError("Another worker holds the installation lease")
                    if current:
                        job = session.get(Job, current)
                        if job.generation != generation or job.cancel_requested:
                            cancel.set()
                        else:
                            job.lease_until = now + 20
                    try:
                        schedule(session, config, now)
                    except ValueError:
                        # Invalid live configuration is not permission to widen scope.
                        pass
                if future and future.done():
                    try:
                        data, args = future.result()
                        with transaction(engine) as session:
                            job = session.get(Job, current)
                            profile = session.get(Profile, job.profile_id)
                            if (
                                not fenced(session, owner, job.generation, time.time())
                                or job.cancel_requested
                            ):
                                raise ValueError("Obsolete or cancelled scan result")
                            run = ingest(
                                session,
                                network_id=job.network_id,
                                data=data,
                                kind=profile.kind,
                                config=config,
                                targets=job.target,
                                run_id=job.id,
                                source="live",
                                observed_at=job.started_at,
                                profile_revision=f"{profile.id}:{profile.revision}",
                                job_id=job.id,
                                arguments=args,
                            )
                            job.status, job.finished_at = (
                                run.status if run.status != "suspect" else "partial",
                                time.time(),
                            )
                    except Exception as exc:
                        with transaction(engine) as session:
                            job = session.get(Job, current)
                            if fenced(session, owner, job.generation, time.time()):
                                job.status = "cancelled" if job.cancel_requested else "failed"
                                job.error = (
                                    str(exc)[:300]
                                    if isinstance(exc, ValueError)
                                    else "Scan execution failed"
                                )
                                job.finished_at = time.time()
                                profile = session.get(Profile, job.profile_id)
                                if profile.kind == "discovery":
                                    reset_misses(session, job.network_id)
                                    # A deliberate cancel says nothing about the scanner's health.
                                    if not job.cancel_requested:
                                        network = session.get(Network, job.network_id)
                                        network.health = "unhealthy"
                                        network.health_reason = job.error
                    current, future = None, None
                dispatch_one(engine, config, provider, now)
                dispatch_test(engine, config, provider, now)
                if not future:
                    with transaction(engine) as session:
                        current = claim(session, owner, generation, time.time())
                    if current:
                        with Session(engine) as session:
                            job = session.get(Job, current)
                            assert job is not None
                            network = session.get(Network, job.network_id)
                            profile = session.get(Profile, job.profile_id)
                            session.expunge(network)
                            session.expunge(profile)
                            target = job.target
                        cancel.clear()
                        future = executor.submit(
                            execute, config, network, profile, target, cancel.is_set
                        )
                if not future and now >= maintenance_at:
                    from network_dragon.operations.backup import backup
                    from network_dragon.operations.retention import cleanup
                    from network_dragon.persistence.models import Setting

                    cleanup(engine, config, now)
                    with Session(engine) as session:
                        last = session.get(Setting, "last_backup")
                        needs_backup = not last or now - last.value["at"] > 86400
                    if needs_backup:
                        backup(config)
                    maintenance_at = now + 3600
                if once and not future:
                    break
                time.sleep(1)
        finally:
            cancel.set()
