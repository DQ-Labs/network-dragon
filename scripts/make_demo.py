"""Create deterministic fixture files and an isolated browser-test DB. No network IO."""
import os
import sys
import time
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from network_dragon.auth.service import set_password
from network_dragon.config import Config
from network_dragon.domain.ingest import ingest
from network_dragon.persistence.db import engine_for, migrate, transaction
from network_dragon.persistence.models import Device, Network
from network_dragon.worker.queue import seed_profiles
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]


def fixture(at, ports=False, changed=False):
    root = Element('nmaprun', version='fixture-1', scanner='nmap')
    if ports:
        SubElement(root, 'scaninfo', protocol='tcp', services='22,80,443,3000,8080')
    names = ['gateway.lab', 'compute-01.lab', 'compute-02.lab', 'storage.lab', 'workstation.lab', 'home-bridge.lab']
    for i, name in enumerate(names, 1):
        host = SubElement(root, 'host')
        SubElement(host, 'status', state='up', reason='arp-response')
        SubElement(host, 'address', addr=f'192.0.2.{i}', addrtype='ipv4')
        # Nmap adds the OUI vendor to the MAC address when it knows one.
        SubElement(host, 'address', addr=f'02:44:52:41:47:0{i}', addrtype='mac', **({'vendor': 'Raspberry Pi Trading'} if i == 6 else {}))
        SubElement(SubElement(host, 'hostnames'), 'hostname', name=name)
        if ports:
            container = SubElement(host, 'ports')
            selected = [(22, 'ssh'), (443, 'https')] + ([(3000, 'http'), (8080, 'http')] if i in [2, 3] else [])
            for number, service in selected:
                p = SubElement(container, 'port', protocol='tcp', portid=str(number))
                state = 'filtered' if changed and i == 3 and number == 8080 else 'closed' if changed and i == 2 and number == 3000 else 'open'
                SubElement(p, 'state', state=state, reason='conn-refused' if state == 'closed' else 'syn-ack')
                SubElement(p, 'service', name=service, method='probed' if number == 22 else 'table', conf='10' if number == 22 else '3', product='OpenSSH' if number == 22 else '', version='9.9' if changed and i == 2 and number == 22 else '9.8' if number == 22 else '')
    stats = SubElement(root, 'runstats')
    SubElement(stats, 'finished', time=str(at), exit='success')
    SubElement(stats, 'hosts', total='256')
    return tostring(root, encoding='utf-8', xml_declaration=True)


def main():
    fixtures = ROOT / 'tests/fixtures/nmap'
    fixtures.mkdir(parents=True, exist_ok=True)
    for name, at, port, change in [('discovery', 1792108800, False, False), ('ports', 1792108860, True, False), ('port-changes', 1792108920, True, True)]:
        (fixtures / f'{name}.xml').write_bytes(fixture(at, port, change))
    if '--browser' not in sys.argv:
        return
    password = os.environ.get('DRAGON_TEST_PASSWORD')
    if not password:
        raise SystemExit('DRAGON_TEST_PASSWORD must be set for isolated browser verification')
    # Unique file per invocation avoids overwriting any existing inventory.
    db = ROOT / f'.tmp/browser-{time.time_ns()}.db'
    config = Config(database=str(db), allow_http_local=True)
    engine = engine_for(config.database)
    migrate(engine)
    now = time.time()
    with transaction(engine) as session:
        seed_profiles(session)
        set_password(session, password)
        network = Network(name='Fixture lab', cidr='192.0.2.0/24', mode='fixture')
        session.add(network)
        session.flush()
        for i, (port, changed) in enumerate([(False, False), (True, False), (True, True)]):
            ingest(session, network_id=network.id, data=fixture(int(now) - 120 + i * 50, port, changed), kind='ports' if port else 'discovery', config=config)
        for i, device in enumerate(session.scalars(select(Device).order_by(Device.ip))):
            device.watched = i < 4
            device.acknowledged = i < 4
    engine.dispose()
    path = ROOT / '.tmp/browser.toml'
    path.write_text(f'database = "{db.as_posix()}"\nallow_http_local = true\nfrontend = "{(ROOT / "frontend/dist").as_posix()}"\n')
    print('Isolated fixture browser database prepared; live scanning and notifications disabled.')


if __name__ == '__main__':
    main()
