"""Post-build smoke test for the bundled backend.

Run against the PyInstaller output, on the OS that produced it. Its job is to
catch bundling failures that a normal `python -m app` run cannot: a missing
hidden import, an unbundled frontend, a broken TLS trust store, a uvicorn
protocol impl that resolved dynamically and therefore wasn't collected.

    python smoke_test.py dist/stat-consultant-backend/stat-consultant-backend

Keyring note. The check below is the one that catches a missing
``win32ctypes`` hidden import — the most likely way this bundle breaks on
Windows, and something a macOS developer machine can never reproduce. But on
macOS the Keychain shows a GUI consent dialog the first time a *new* signing
identity reads an item, and PyInstaller ad-hoc signs every build with a fresh
identity. A CI runner has nobody to click it, so a real round-trip there would
hang until the job times out. Hence: real round-trip on Windows (Credential
Manager is headless), import-only check on macOS.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
IS_WINDOWS = sys.platform == "win32"


class SmokeFailure(AssertionError):
    pass


def check(condition: object, label: str) -> None:
    if not condition:
        raise SmokeFailure(label)
    print(f"  ok   {label}")


def get(path: str, timeout: float = 10) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def wait_for_health(proc: subprocess.Popen, timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SmokeFailure(f"backend exited early (code {proc.returncode})")
        try:
            status, body = get("/health", timeout=2)
            if status == 200:
                return json.loads(body)
        except Exception:
            time.sleep(0.5)
    raise SmokeFailure(f"backend did not become healthy within {timeout}s")


def check_websocket() -> None:
    """Handshake only — proves the ws protocol impl made it into the bundle."""
    import base64
    import socket

    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET /ws/consult HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\n"
        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    with socket.create_connection(("127.0.0.1", PORT), timeout=10) as sock:
        sock.sendall(request.encode())
        response = sock.recv(4096).decode("latin-1")
    check("101" in response.split("\r\n")[0], "WS /ws/consult upgrades (101)")


def check_keyring() -> None:
    if not IS_WINDOWS:
        # Import-only: see the module docstring on the macOS Keychain dialog.
        status, body = get("/api/settings/keys")
        check(status == 200, "GET /api/settings/keys responds (keyring imports)")
        check(b"provider" in body, "settings payload shape")
        return

    # Windows: a real round-trip through the Credential Manager. This is the
    # check that fails loudly if win32ctypes wasn't bundled.
    import urllib.request as req

    payload = json.dumps({"provider": "anthropic", "api_key": "smoke-test-dummy"})
    r = req.Request(
        BASE + "/api/settings/keys",
        data=payload.encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with req.urlopen(r, timeout=20) as resp:
        check(resp.status == 200, "POST /api/settings/keys stores a key")

    status, body = get("/api/settings/keys")
    providers = {p["provider"]: p["has_key"] for p in json.loads(body)["providers"]}
    check(providers.get("anthropic") is True, "stored key reads back (win32ctypes ok)")

    r = req.Request(BASE + "/api/settings/keys/anthropic", method="DELETE")
    with req.urlopen(r, timeout=20) as resp:
        check(resp.status in (200, 204), "DELETE /api/settings/keys removes it")

    status, body = get("/api/settings/keys")
    providers = {p["provider"]: p["has_key"] for p in json.loads(body)["providers"]}
    check(providers.get("anthropic") is False, "key is gone after delete")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: smoke_test.py <path-to-backend-executable>", file=sys.stderr)
        return 2
    exe = Path(sys.argv[1]).resolve()
    if not exe.is_file():
        print(f"not found: {exe}", file=sys.stderr)
        return 2

    state_dir = Path(tempfile.mkdtemp(prefix="sc-smoke-"))
    env = dict(os.environ)
    if not IS_WINDOWS:
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"

    print(f"launching {exe}")
    proc = subprocess.Popen(
        [str(exe), "--port", str(PORT), "--state-dir", str(state_dir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    try:
        health = wait_for_health(proc)
        print("health:", health)

        check(health.get("status") == "ok", "/health reports ok")
        check(
            Path(health.get("state_dir", "")).resolve() == state_dir.resolve(),
            "--state-dir is honoured and echoed by /health",
        )
        check((state_dir / "rstudio_token").is_file(), "RStudio token written")

        status, body = get("/")
        html = body.decode("utf-8", "replace")
        check(status == 200, "GET / serves the bundled frontend")
        check("<title>" in html, "index.html is real HTML")
        check("/assets/" in html, "index.html references a built asset")

        asset = html.split('src="', 1)[1].split('"', 1)[0]
        status, _ = get(asset)
        check(status == 200, f"bundled asset is served ({asset})")

        status, _ = get("/api/definitely-not-a-route")
        check(status == 404, "unmatched /api path 404s instead of returning HTML")

        check_websocket()
        check_keyring()

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\nsmoke test passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SmokeFailure as exc:
        print(f"\nSMOKE TEST FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
