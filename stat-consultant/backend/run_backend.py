"""Entry point for the bundled backend.

Deliberately separate from ``app/main.py``: CLI parsing and uvicorn
configuration belong outside the app module, and ``--state-dir`` has to reach
the environment *before* ``app`` is imported (``app.paths`` reads
``STAT_CONSULTANT_HOME``, and the app writes the RStudio token at import time).

Run directly in dev, or as the PyInstaller-built executable in the shipped app:

    python run_backend.py --port 8000
    stat-consultant-backend --state-dir "C:/Users/me/.stat-consultant"
"""

from __future__ import annotations

import argparse
import os
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="stat-consultant-backend")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="loopback by default; binding 0.0.0.0 triggers the Windows "
        "firewall prompt and exposes the app to the network",
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help="where to keep the RStudio token, conversations and references. "
        "The R launcher passes its own resolved path so both sides agree.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="enable permissive localhost CORS for a browser pointed straight "
        "at this port (not needed behind the Vite proxy)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Both must be set before `app` is imported — see the module docstring.
    if args.state_dir:
        os.environ["STAT_CONSULTANT_HOME"] = args.state_dir
    if args.dev:
        os.environ["STAT_CONSULTANT_DEV_CORS"] = "1"

    import uvicorn

    from app.main import app

    # Pass the app object rather than "app.main:app", and pin loop/http/ws
    # explicitly. uvicorn's "auto" defaults resolve those by importing module
    # paths at runtime, which PyInstaller's static analysis cannot see — the
    # single most common way a bundled uvicorn fails to start.
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        loop="asyncio",
        http="h11",
        ws="websockets",
        lifespan="on",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
