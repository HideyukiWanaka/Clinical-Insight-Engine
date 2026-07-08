"""WS /ws/console — R console output stream (§4.1, RT-004).

Auth is via the first message (``{"token": ...}``, §2), not the HTTP
``X-CIE-Token`` middleware. When the first message also carries an
``r_script``, it is executed through ``RuntimeAgent`` and its **sanitized**
stdout is streamed (``ContextGuard.sanitize_stdout``); raw output is never sent.

The local executor is batch (it returns a sanitized summary after the run
completes), so Phase 1 streams that sanitized summary line-by-line followed by
an ``exit`` frame — the same contract a future incremental executor will honor.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from cie.api.deps import invoke_agent, new_execution_id
from cie.security.capability_token import CapabilityScope

_log = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])


@router.websocket("/ws/console")
async def ws_console(websocket: WebSocket) -> None:
    """Authenticate, run the supplied R script, and stream sanitized stdout."""
    await websocket.accept()
    services = websocket.app.state.services
    expected = websocket.app.state.session_token

    try:
        first = await websocket.receive_json()
    except (WebSocketDisconnect, ValueError):
        await websocket.close(code=1008)
        return

    provided = str(first.get("token", ""))
    if not provided or not secrets.compare_digest(provided, expected):
        await websocket.send_json(
            {"type": "stderr", "text": "unauthorized: invalid session token", "exit_code": None}
        )
        await websocket.close(code=1008)  # policy violation
        return

    r_script = first.get("r_script")
    if not r_script:
        # Subscribed but nothing to run yet — acknowledge and close cleanly.
        await websocket.send_json({"type": "exit", "text": "", "exit_code": None})
        await websocket.close()
        return

    # Same quota shape as POST /api/run (OWASP A04:2025) — this route bypasses
    # RateLimitMiddleware entirely since BaseHTTPMiddleware never sees
    # "websocket"-scope connections, so it has to self-limit.
    client = websocket.client.host if websocket.client else "unknown"
    retry_after = websocket.app.state.ws_rate_limiter.check(
        client, "/ws/console", max_requests=20, window_seconds=60
    )
    if retry_after is not None:
        await websocket.send_json(
            {"type": "stderr", "text": "rate limited: too many executions, "
             f"retry in {int(retry_after)}s", "exit_code": None}
        )
        await websocket.close(code=1008)
        return

    execution_id = first.get("execution_id") or new_execution_id()
    context_guard = services["context_guard"]

    try:
        output = await invoke_agent(
            services,
            agent_key="runtime_agent",
            agent_id="runtime",
            step_id="ws_console",
            scopes=[
                CapabilityScope.RUNTIME_INVOKE_EXECUTION,
                CapabilityScope.AUDIT_WRITE_ENTRY,
            ],
            payload={"r_script": r_script, "inject_raw_data_rows": False},
            input_schema_ref="cie://schemas/task-context.schema.json",
            execution_id=execution_id,
        )
    except Exception as exc:  # noqa: BLE001 — never leak a raw traceback to the socket
        _log.warning("ws_console execution error: %s", exc)
        await websocket.send_json(
            {"type": "stderr", "text": "execution error", "exit_code": None}
        )
        await websocket.close(code=1011)
        return

    if output.status != "success":
        await websocket.send_json(
            {"type": "stderr", "text": output.error_message or "execution failed",
             "exit_code": None}
        )
        await websocket.send_json({"type": "exit", "text": "", "exit_code": 1})
        await websocket.close()
        return

    execution_result = output.output_payload.get("execution_result") or {}
    summary = execution_result.get("sanitized_stdout_summary", "") or ""
    # Idempotent re-sanitize at the API boundary — explicit RT-004 guarantee.
    summary = await context_guard.sanitize_stdout(summary, execution_id)

    for line in summary.splitlines() or [""]:
        await websocket.send_json({"type": "stdout", "text": line, "exit_code": None})

    exit_code = execution_result.get("exit_code")
    await websocket.send_json({"type": "exit", "text": "", "exit_code": exit_code})
    await websocket.close()
