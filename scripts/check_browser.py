"""Start an isolated fixture app, run browser checks, and stop only our server."""
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    environment = dict(os.environ)
    environment["DRAGON_TEST_PASSWORD"] = secrets.token_urlsafe(32)
    environment["PYTHONUTF8"] = "1"
    environment["NETWORK_DRAGON_CONFIG"] = str(ROOT / ".tmp/browser.toml")
    subprocess.run([sys.executable, "scripts/make_demo.py", "--browser"], cwd=ROOT, env=environment, check=True)
    # Use a dedicated local port so a user's development server is left alone.
    environment["DRAGON_TEST_BASE_URL"] = "http://127.0.0.1:8765"
    with (ROOT / ".tmp/browser-server.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen([sys.executable, "-m", "network_dragon.cli", "web", "--port", "8765"], cwd=ROOT, env=environment, stdout=log, stderr=log,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            ready = False
            with httpx.Client(timeout=1, trust_env=False) as client:
                for _ in range(60):
                    if server.poll() is not None:
                        raise RuntimeError("Fixture server exited; inspect .tmp/browser-server.log")
                    try:
                        ready = client.get(environment["DRAGON_TEST_BASE_URL"] + "/health/ready").status_code == 200
                    except httpx.HTTPError:
                        pass
                    if ready:
                        break
                    time.sleep(.25)
            if not ready:
                raise RuntimeError("Fixture server did not become ready")
            subprocess.run(["node", "node_modules/@playwright/test/cli.js", "test"], cwd=ROOT / "frontend", env=environment, check=True)
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    main()
