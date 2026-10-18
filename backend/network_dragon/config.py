import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str = "data/app.db"
    frontend: str = "frontend/dist"
    allow_http_local: bool = False
    trusted_proxy_ips: list[str] = Field(default_factory=list)
    live_scanning: bool = False
    notifications: bool = False
    allowed_cidrs: list[str] = Field(default_factory=list)
    allowed_interfaces: list[str] = Field(default_factory=list)
    # Addresses never scanned or recorded, e.g. a honeypot that alerts on any probe.
    excluded_addresses: list[str] = Field(default_factory=list)
    # MACs expected to answer for several addresses (e.g. a router); others are conflicts.
    multihomed_macs: list[str] = Field(default_factory=list)
    nmap: str = "nmap"
    max_targets: int = Field(default=256, ge=1, le=256)
    discovery_seconds: int = Field(default=120, ge=30, le=86400)
    ports_seconds: int = Field(default=900, ge=120, le=86400)
    routine_ports: str = "top1000"
    routine_budget_seconds: int = Field(default=60, ge=10, le=180)
    offline_misses: int = Field(default=3, ge=2, le=20)
    offline_seconds: int = Field(default=300, ge=60, le=86400)
    cooldown_seconds: int = Field(default=600, ge=0, le=86400)
    retention_observations_days: int = Field(default=30, ge=1, le=3650)
    retention_events_days: int = Field(default=365, ge=30, le=3650)
    retention_delivery_days: int = Field(default=90, ge=1, le=3650)
    backup_directory: str = "data/backups"
    timezone: str = "UTC"

    @field_validator("routine_ports")
    @classmethod
    def validate_ports(cls, value):
        if value != "top1000":
            from network_dragon.scanner.validation import ports

            ports(value)
        return value

    @field_validator("trusted_proxy_ips")
    @classmethod
    def validate_proxies(cls, value):
        from ipaddress import ip_address

        return [str(ip_address(item)) for item in value]

    @field_validator("excluded_addresses")
    @classmethod
    def validate_excluded(cls, value):
        from ipaddress import IPv4Address

        return sorted({str(IPv4Address(item)) for item in value}, key=IPv4Address)

    @field_validator("multihomed_macs")
    @classmethod
    def validate_macs(cls, value):
        import re

        macs = {item.upper().replace("-", ":") for item in value}
        if any(not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac) for mac in macs):
            raise ValueError("multihomed_macs entries must be MAC addresses")
        return sorted(macs)


def load_config() -> Config:
    path = os.environ.get("NETWORK_DRAGON_CONFIG")
    return Config(**(tomllib.loads(Path(path).read_text(encoding="utf-8")) if path else {}))


def secret(name: str) -> str:
    path = os.environ.get(f"{name}_FILE")
    return Path(path).read_text().strip() if path else os.environ.get(name, "").strip()
