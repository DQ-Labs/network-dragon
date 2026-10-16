import pytest
from network_dragon.config import Config
from network_dragon.persistence.db import engine_for, migrate, transaction
from network_dragon.persistence.models import Network
from network_dragon.worker.queue import seed_profiles


@pytest.fixture
def env(tmp_path):
    config = Config(
        database=str(tmp_path / "app.db"),
        backup_directory=str(tmp_path / "backups"),
        notifications=True,
        allow_http_local=True,
        cooldown_seconds=0,
    )
    engine = engine_for(config.database)
    migrate(engine)
    with transaction(engine) as session:
        network = Network(name="Test scope", cidr="192.0.2.0/29", mode="fixture")
        session.add(network)
        session.flush()
        network_id = network.id
        seed_profiles(session)
    yield engine, config, network_id
    engine.dispose()


def xml(hosts=None, *, coverage="", complete=True, total=8, at=1000, aggregates="", timeout=False):
    from xml.sax.saxutils import quoteattr

    hosts = [("192.0.2.1", "02:00:00:00:00:01", [])] if hosts is None else hosts
    elements = []
    for ip, mac, observations in hosts:
        elements.append(
            f'<host timedout="{str(timeout).lower()}"><status state="up"/><address addr="{ip}" addrtype="ipv4"/>'
        )
        if mac:
            elements.append(f'<address addr="{mac}" addrtype="mac"/>')
        elements.append("<ports>")
        for number, state, service in observations:
            attrs = " ".join(f"{k}={quoteattr(v)}" for k, v in service.items())
            elements.append(
                f'<port protocol="tcp" portid="{number}"><state state="{state}" reason="test"/><service {attrs}/></port>'
            )
        elements.append(aggregates + "</ports></host>")
    info = f'<scaninfo protocol="tcp" services="{coverage}"/>' if coverage else ""
    return (
        f'<nmaprun version="fixture-1">{info}{"".join(elements)}<runstats><finished time="{at}" exit="{"success" if complete else "error"}"/><hosts total="{total}"/></runstats></nmaprun>'
    ).encode()


@pytest.fixture
def ingest_run(env):
    from network_dragon.domain.ingest import ingest

    engine, config, network_id = env
    counter = 0

    def run(data=None, **kwargs):
        nonlocal counter
        counter += 1
        with transaction(engine) as session:
            result = ingest(
                session,
                network_id=network_id,
                data=data or xml(at=1000 + counter * 120),
                kind=kwargs.pop("kind", "discovery"),
                config=config,
                run_id=kwargs.pop("run_id", str(counter)),
                **kwargs,
            )
            return result.id

    return run
