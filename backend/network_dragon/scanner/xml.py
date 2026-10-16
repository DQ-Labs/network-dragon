import re
from dataclasses import asdict, dataclass, field
from ipaddress import ip_address

from defusedxml import ElementTree

from network_dragon.scanner.validation import ports

MAX_XML = 8 * 1024 * 1024
STATES = {"open", "closed", "filtered", "unfiltered", "open|filtered", "closed|filtered"}


@dataclass
class Port:
    port: int
    state: str
    reason: str = ""
    protocol: str = "tcp"
    name: str = ""
    method: str = ""
    confidence: str = ""
    product: str = ""
    version: str = ""

    def facts(self):
        return asdict(self)


@dataclass
class Host:
    ip: str
    mac: str | None
    hostname: str
    up: bool
    complete: bool
    ports: list[Port] = field(default_factory=list)
    aggregate_state: str | None = None


@dataclass
class Scan:
    hosts: list[Host]
    coverage: set[int]
    complete: bool
    version: str
    total: int
    observed_at: float


def parse_xml(data: bytes) -> Scan:
    if len(data) > MAX_XML:
        raise ValueError("XML exceeds the 8 MiB limit")
    root = ElementTree.fromstring(data)
    if root.tag != "nmaprun":
        raise ValueError("Expected Nmap XML")
    finished = root.find("runstats/finished")
    complete = finished is not None and finished.get("exit") == "success"
    coverage: set[int] = set()
    for info in root.findall("scaninfo"):
        if info.get("protocol") == "tcp":
            coverage |= ports(info.get("services", ""))
    hosts = []
    for element in root.findall("host"):
        address = element.find("address[@addrtype='ipv4']")
        if address is None:
            continue
        ip = str(ip_address(address.get("addr", "")))
        mac_el = element.find("address[@addrtype='mac']")
        mac = mac_el.get("addr", "").upper().replace("-", ":") if mac_el is not None else None
        if mac and not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac):
            raise ValueError("Invalid MAC evidence")
        name = element.find("hostnames/hostname")
        status = element.find("status")
        host = Host(
            ip,
            mac,
            name.get("name", "")[:255] if name is not None else "",
            status is not None and status.get("state") == "up",
            complete and element.get("timedout", "false") != "true",
        )
        for entry in element.findall("ports/port"):
            if entry.get("protocol") != "tcp":
                continue
            number = int(entry.get("portid", "0"))
            state = entry.find("state")
            if number not in coverage or state is None or state.get("state") not in STATES:
                continue
            service = entry.find("service")
            facts = {
                key: service.get(attr, "")[:512] if service is not None else ""
                for key, attr in [
                    ("name", "name"),
                    ("method", "method"),
                    ("confidence", "conf"),
                    ("product", "product"),
                    ("version", "version"),
                ]
            }
            host.ports.append(
                Port(number, state.get("state", ""), state.get("reason", "")[:120], **facts)
            )
        aggregates = element.findall("ports/extraports")
        # A single aggregate covering exactly the omitted set is unambiguous.
        explicit = {p.port for p in host.ports}
        if host.complete and len(aggregates) == 1 and len(explicit) == len(host.ports):
            aggregate = aggregates[0]
            if (
                int(aggregate.get("count", "0")) == len(coverage - explicit)
                and aggregate.get("state") in STATES
            ):
                host.aggregate_state = aggregate.get("state")
        hosts.append(host)
    totals = root.find("runstats/hosts")
    return Scan(
        hosts,
        coverage,
        complete,
        root.get("version", "unknown")[:80],
        int(totals.get("total", "0")) if totals is not None else 0,
        float(finished.get("time", "0")) if finished is not None else 0,
    )
