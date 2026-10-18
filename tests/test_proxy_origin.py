"""`tailscale serve --https=8443 http://127.0.0.1:8000` against the real CLI web server.

Tailscale's reverse proxy (ipn/ipnlocal/serve.go, addProxyForwardedHeaders) keeps the
client's Host, sets X-Forwarded-Host to it, sets X-Forwarded-Proto: https for TLS
listeners, and replaces X-Forwarded-For with the tailnet client address. It connects
to the backend from 127.0.0.1.
"""

import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from network_dragon.auth.service import set_password
from network_dragon.persistence.db import engine_for, migrate, transaction

PUBLIC = "dragon.lonk-dorian.ts.net:8443"
PASSWORD = "proxy-test-password"
SERVE_HEADERS = {
    "Host": PUBLIC,
    "X-Forwarded-Host": PUBLIC,
    "X-Forwarded-Proto": "https",
    "X-Forwarded-For": "100.101.102.103",
    "Origin": f"https://{PUBLIC}",
    "Content-Type": "application/json",
}


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def serve(tmp_path):
    servers = []

    def start(trusted):
        root = tmp_path / str(len(servers))
        root.mkdir()
        database = root / "app.db"
        config = root / "config.toml"
        config.write_text(
            f"database = {str(database)!r}\n"
            f"frontend = {str(root / 'dist')!r}\n"
            f"trusted_proxy_ips = {trusted!r}\n",
            encoding="utf-8",
        )
        engine = engine_for(str(database))
        migrate(engine)
        with transaction(engine) as session:
            set_password(session, PASSWORD)
        engine.dispose()
        port = free_port()
        backend = str(Path(__file__).resolve().parents[1] / "backend")
        env = {
            **os.environ,
            "NETWORK_DRAGON_CONFIG": str(config),
            "PYTHONPATH": os.pathsep.join(filter(None, [backend, os.environ.get("PYTHONPATH")])),
        }
        process = subprocess.Popen(
            [sys.executable, "-m", "network_dragon.cli", "web", "--port", str(port)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        servers.append(process)
        deadline = time.monotonic() + 20
        while True:
            try:
                if request(port, "GET", "/health/live", {})[0] == 200:
                    return port
            except OSError:
                pass
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(process.stderr.read().decode() if process.stderr else "")
            time.sleep(0.1)

    yield start
    for process in servers:
        process.terminate()
        process.wait(timeout=10)


def request(port, method, path, headers, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.getheader("set-cookie") or "", response.read()
    finally:
        connection.close()


def sign_in(port, headers):
    return request(port, "POST", "/api/v1/session", headers, f'{{"password": "{PASSWORD}"}}')


def test_tailscale_serve_headers_pass_origin_check(serve):
    port = serve(["127.0.0.1"])
    status, cookie, body = sign_in(port, SERVE_HEADERS)
    assert status == 200, body
    assert "Secure" in cookie and "HttpOnly" in cookie
    csrf = json.loads(body)["csrf"]
    token = cookie.split(";", 1)[0]
    status, _, body = request(
        port,
        "DELETE",
        "/api/v1/session",
        {**SERVE_HEADERS, "Cookie": token, "X-CSRF-Token": csrf},
    )
    assert status == 200, body


@pytest.mark.parametrize(
    "change",
    [
        {"X-Forwarded-Proto": None},
        {"Origin": "https://evil.example"},
        {"Origin": "https://dragon.lonk-dorian.ts.net"},
    ],
)
def test_origin_check_still_rejects_mismatches(serve, change):
    port = serve(["127.0.0.1"])
    headers = {k: v for k, v in {**SERVE_HEADERS, **change}.items() if v is not None}
    status, _, body = sign_in(port, headers)
    assert status == 403 and b"Cross-origin" in body


def test_forwarded_proto_from_untrusted_source_is_ignored(serve):
    port = serve(["127.0.0.2"])
    status, _, body = sign_in(port, SERVE_HEADERS)
    assert status == 403 and b"Cross-origin" in body
