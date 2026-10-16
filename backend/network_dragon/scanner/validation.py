import ipaddress
import re

from network_dragon.config import Config


def scope(value: str, maximum: int = 256) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as exc:
        raise ValueError("Use a numeric IPv4 address or canonical CIDR") from exc
    if network.version != 4 or network.num_addresses > maximum:
        raise ValueError(f"IPv4 scope must contain at most {maximum} addresses")
    if network.is_multicast or network.is_unspecified or network.is_loopback:
        raise ValueError("Multicast, unspecified, and loopback scopes are unsupported")
    return network


def validate_live(target: str, network, config: Config) -> None:
    if not config.live_scanning or network.mode != "live" or not network.enabled:
        raise ValueError("Live scanning requires explicit installation and network configuration")
    requested = scope(target, config.max_targets)
    monitored = scope(network.cidr, config.max_targets)
    allowed = [scope(item, config.max_targets) for item in config.allowed_cidrs]
    if not requested.subnet_of(monitored) or not any(monitored.subnet_of(n) for n in allowed):
        raise ValueError("Target is outside the installation allowlist")
    if network.interface not in config.allowed_interfaces or not re.fullmatch(
        r"[A-Za-z0-9_.:-]{1,32}", network.interface
    ):
        raise ValueError("Interface must be explicitly allowlisted")


def ports(value: str) -> set[int]:
    result: set[int] = set()
    if not value or len(value) > 65536:
        raise ValueError("Provide TCP ports/ranges")
    for segment in value.split(","):
        if not re.fullmatch(r"\d{1,5}(-\d{1,5})?", segment):
            raise ValueError("Invalid TCP port list")
        bounds = list(map(int, segment.split("-")))
        lo, hi = bounds[0], bounds[-1]
        if not 1 <= lo <= hi <= 65535:
            raise ValueError("Ports must be between 1 and 65535")
        result.update(range(lo, hi + 1))
    return result
