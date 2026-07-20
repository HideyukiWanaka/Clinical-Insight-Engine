"""REST /api/environment/sync — transparent environment sync receiver (Step 7).

The RStudio Addin scans ``ls(.GlobalEnv)`` and POSTs an **aggregate-only**
snapshot of each data.frame (SPEC §9.1): column names, types, missing counts,
and — for categorical columns — the distinct count and anonymised group sizes.
Category *label strings* are never sent (they are raw cell values); raw
row/cell values are never sent either. The wire schema below has no field that
can carry a label, so even a buggy/old/hostile Addin cannot push one through.

The Addin already drops PII columns before sending (SPEC §9.2); this endpoint
runs the column-name check again as a server-side second layer, stores the
filtered snapshot on ``app.state.environment`` (consumed by Step 8), and logs a
one-line summary so the sync is visible in the uvicorn console.

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


class Column(BaseModel):
    """A single column's aggregate metadata (no raw values, no level labels).

    ``n_distinct`` is the number of distinct non-NA values; ``level_counts`` is
    the anonymised group sizes (top-10, sorted desc) with no labels attached.
    There is deliberately no field for a category label string.
    """

    name: str
    type: str
    n_missing: int
    n_distinct: int | None = None
    level_counts: list[int] | None = None


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
    """Return a copy of *obj* with any PII-tripping column removed (double-check).

    Only the column *name* can be checked server-side — level labels never reach
    the backend (the schema has no field for them), so the value-pattern check
    runs Addin-side only, before send.
    """
    kept = [col for col in obj.columns if not column_has_pii(col.name)]
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
