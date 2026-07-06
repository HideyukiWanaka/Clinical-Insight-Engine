"""POST /api/workspace/reset — clear the persisted R workspace.

Implements the "ワークスペースをリセット" control from
``spec/runtime-workspace-persistence.md`` §3: physically delete the ``.RData``
image and ``workspace_summary.json`` under the runtime OUTPUT_DIR so the next
run starts from an empty workspace.

This is an ordinary file deletion of a visible convenience cache — it is NOT
governed by the knowledge soft-delete rule (ADR-0003), which applies only to
``knowledge/institutional/`` entries (spec §3).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from cie.api.deps import get_services
from cie.api.models import WorkspaceResetResponse
from cie.runtime.workspace_wrapper import RDATA_FILENAME, WORKSPACE_SUMMARY_FILENAME

router = APIRouter(prefix="/api", tags=["workspace"])


@router.post("/workspace/reset", response_model=WorkspaceResetResponse)
async def reset_workspace(request: Request) -> WorkspaceResetResponse:
    """Delete the persisted ``.RData`` and ``workspace_summary.json``.

    Returns the list of files actually removed (empty when nothing was
    persisted yet — a reset with no prior state is a no-op, not an error).
    """
    services = get_services(request)
    output_dir = services.get("r_output_dir")

    removed: list[str] = []
    if output_dir is not None:
        output_dir = Path(output_dir)
        for name in (RDATA_FILENAME, WORKSPACE_SUMMARY_FILENAME):
            target = output_dir / name
            if target.is_file():
                target.unlink()
                removed.append(name)

    return WorkspaceResetResponse(removed=removed)
