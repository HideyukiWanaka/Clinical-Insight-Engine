"""REST /api/environment/sync — transparent environment sync receiver (Step 7).

The RStudio Addin scans ``ls(.GlobalEnv)`` and POSTs an **aggregate-only**
snapshot of each data.frame (SPEC §9.1): column names, types, missing counts,
and factor/categorical level labels+counts. Raw row/cell values are never sent
(``inject_raw_data_rows = False``, CLAUDE.md).

The Addin already drops PII columns before sending (SPEC §9.2); this endpoint
runs the same check again as a server-side second layer, stores the filtered
snapshot on ``app.state.environment`` (consumed by Step 8), and logs a one-line
summary so the sync is visible in the uvicorn console.

Auth: gated by the local shared secret (same Addin-only boundary as
``GET /api/rstudio/pending`` — see ``rstudio_auth.py``). A same-origin browser
page cannot read the secret file, so it cannot inject fake environment data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .pii import column_has_pii
from .rstudio_auth import require_rstudio_token

router = APIRouter(prefix="/api/environment", tags=["environment"])


class Level(BaseModel):
    """One aggregated category level of a factor/categorical column."""

    label: str
    count: int


class Column(BaseModel):
    """A single column's aggregate metadata (no raw values)."""

    name: str
    type: str
    n_missing: int
    levels: list[Level] | None = None


class RObject(BaseModel):
    """One data.frame-like object from the user's GlobalEnv."""

    name: str
    # ``class`` is a Python keyword — accept it from the wire via an alias.
    class_: str = Field(alias="class")
    nrow: int
    columns: list[Column]

    model_config = {"populate_by_name": True}


class EnvironmentSnapshot(BaseModel):
    """The full §9.1 payload the Addin sends."""

    objects: list[RObject]


def _filter_object(obj: RObject) -> RObject:
    """Return a copy of *obj* with any PII-tripping column removed (double-check)."""
    kept = [
        col
        for col in obj.columns
        if not column_has_pii(
            col.name,
            [lvl.label for lvl in col.levels] if col.levels else None,
        )
    ]
    return obj.model_copy(update={"columns": kept})


@router.post("/sync", dependencies=[Depends(require_rstudio_token)])
def sync(snapshot: EnvironmentSnapshot, request: Request) -> dict[str, object]:
    """Receive, PII-double-check, store, and log an environment snapshot."""
    filtered = [_filter_object(obj) for obj in snapshot.objects]
    dropped = sum(
        len(before.columns) - len(after.columns)
        for before, after in zip(snapshot.objects, filtered)
    )

    stored = {"objects": [obj.model_dump(by_alias=True) for obj in filtered]}
    request.app.state.environment.update(stored)

    # print (not logging.info) so the line is guaranteed visible in the uvicorn
    # console — matches rstudio_auth.py's existing "[stat-consultant]" prefix.
    summary = ", ".join(
        f"{obj.name}({obj.class_}, {obj.nrow} rows, {len(obj.columns)} cols)"
        for obj in filtered
    )
    print(
        f"[stat-consultant] environment sync: {len(filtered)} object(s) "
        f"[{summary}]; {dropped} column(s) dropped by backend PII check"
    )
    return {
        "status": "ok",
        "objects": len(filtered),
        "columns_dropped": dropped,
    }
