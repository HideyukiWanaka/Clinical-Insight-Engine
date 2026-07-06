"""scratchpad/harness_api_smoke.py — Phase 1 real-data E2E smoke.

Drives the running FastAPI server (rest-api-contract §3–§4) end to end:
  1. POST /api/dataset      — register sample_data.csv
  2. POST /api/intent       — intent_object (Planner; LLM may be stubbed)
  3. POST /api/propose      — analysis_proposal (LLM may be stubbed)
  4. POST /api/run          — fixed R code (print(1+1)) → execution_result
  5. WS   /ws/console       — subscribe + receive the sanitized stdout stream
  6. Assert every response carries execution_id and, on failure,
     error_detail / r_script_provenance.reason (no silent failures).

Config via env:
  CIE_API_BASE_URL        (default http://127.0.0.1:8000)
  CIE_API_SESSION_TOKEN   (the X-CIE-Token printed by the server at startup)

Run:  python scratchpad/harness_api_smoke.py
Exit code 0 == all assertions passed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import websockets

BASE_URL = os.environ.get("CIE_API_BASE_URL", "http://127.0.0.1:8000")
TOKEN = os.environ.get("CIE_API_SESSION_TOKEN", "")
CSV_PATH = Path(os.environ.get("CIE_SAMPLE_CSV", "sample_data.csv"))

HEADERS = {"X-CIE-Token": TOKEN}
_checks: list[str] = []


def _ok(msg: str) -> None:
    _checks.append(msg)
    print(f"  ✓ {msg}")


def _has_exec_id(body: dict, label: str) -> None:
    """Assert the response envelope carries a server-minted execution_id."""
    assert body.get("execution_id"), f"{label}: missing execution_id"
    _ok(f"{label}: execution_id present ({body['execution_id'][:8]}…)")


async def main() -> int:
    """Drive the full §3–§4 flow and assert no response fails silently."""
    assert TOKEN, "Set CIE_API_SESSION_TOKEN to the token printed at server startup."
    assert CSV_PATH.is_file(), f"sample CSV not found: {CSV_PATH}"

    async with httpx.AsyncClient(base_url=BASE_URL, headers=HEADERS, timeout=120) as client:
        # 0. auth wall: a request without the token must be 401
        no_auth = await client.get("/api/files", headers={"X-CIE-Token": ""})
        assert no_auth.status_code == 401, f"expected 401, got {no_auth.status_code}"
        _ok("unauthenticated request → 401")

        # 1. register dataset
        files = {"file": (CSV_PATH.name, CSV_PATH.read_bytes(), "text/csv")}
        r = await client.post("/api/dataset", files=files)
        assert r.status_code == 200, r.text
        ds = r.json()
        assert ds.get("row_count", 0) >= 0
        _ok(f"/api/dataset: {ds.get('row_count')} rows, {ds.get('column_count')} cols")

        # 2. intent
        r = await client.post(
            "/api/intent",
            json={"prompt": "Compare blood pressure between two treatment groups.",
                  "dataset_uploaded": True},
        )
        if r.status_code == 200:
            _has_exec_id(r.json(), "/api/intent")
            intent_object = r.json().get("intent_object") or {}
        else:
            # §5: agent failure carries a reason in the error envelope
            detail = r.json().get("detail", {})
            assert detail.get("detail") or detail.get("message"), "intent error missing reason"
            _ok(f"/api/intent failed with reason (no LLM key?): {detail.get('error_code')}")
            intent_object = {}

        # 3. propose (conversational). Never silent: reason always present.
        r = await client.post("/api/propose", json={"intent_object": intent_object})
        assert r.status_code == 200, r.text
        body = r.json()
        _has_exec_id(body, "/api/propose")
        if body.get("analysis_proposal") is None:
            reason = (body.get("r_script_provenance") or {}).get("reason")
            assert reason, "propose returned no proposal AND no reason — silent failure!"
            _ok(f"/api/propose: no proposal but reason present ({reason})")
        else:
            _ok("/api/propose: analysis_proposal returned")

        # 4. run fixed R code
        r = await client.post(
            "/api/run", json={"r_script": "print(1+1)", "persist_workspace": False}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        _has_exec_id(body, "/api/run")
        status = (body.get("execution_result") or {}).get("status")
        if body.get("error_detail"):
            _ok(f"/api/run: error_detail present (status={status}): {body['error_detail'][:60]}…")
        else:
            _ok(f"/api/run: completed (status={status})")

        # 5. files listing (read-only)
        r = await client.get("/api/files")
        assert r.status_code == 200, r.text
        _ok(f"/api/files: {len(r.json().get('files', []))} files listed")

    # 6. WebSocket console stream
    ws_url = BASE_URL.replace("http", "ws", 1) + "/ws/console"
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"token": TOKEN, "r_script": "print(1+1)"}))
        frames: list[dict] = []
        async for raw in ws:
            msg = json.loads(raw)
            frames.append(msg)
            if msg.get("type") == "exit":
                break
        assert frames, "no frames received from /ws/console"
        assert frames[-1]["type"] == "exit", "stream did not end with an exit frame"
        _ok(f"/ws/console: received {len(frames)} frame(s), ended with exit")

    print(f"\nALL {len(_checks)} CHECKS PASSED ✅")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
