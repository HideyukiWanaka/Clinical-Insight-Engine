"""GET /api/files (+ /content) — read-only workspace file access (§3.6, §3.7).

Reuses the scan logic of ``cie/ui/components/file_browser.py`` (read-only, no
writes/deletes). Path traversal is forbidden: ``path`` is normalised and must
resolve under ``workspace_dir`` (§3.7).

``POST /api/files`` is the one intake exception to the read-only rule: it adds
a user-chosen local file under ``uploads/`` (never overwriting, no deletes) so
users can bring their own R scripts / auxiliary files into the workspace.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from cie.api.deps import get_services
from cie.api.models import FileContentResponse, FileEntry, FilesResponse
from cie.api.upload_limits import read_upload_bounded

router = APIRouter(prefix="/api", tags=["files"])

_MAX_FILES = 200
_TEXT_SUFFIXES = {".r", ".json", ".txt", ".log", ".csv", ".md"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_MAX_PREVIEW_BYTES = 200_000
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_UPLOADS_SUBDIR = "uploads"


def _workspace_root(services: dict) -> Path:
    return Path(services["workspace_dir"]).resolve()


def _kind(suffix: str) -> str:
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _TEXT_SUFFIXES:
        return "text"
    return "other"


@router.get("/files", response_model=FilesResponse)
async def list_files(request: Request) -> FilesResponse:
    """List files under the workspace directory (most-recent first)."""
    root = _workspace_root(get_services(request))
    if not root.is_dir():
        return FilesResponse(files=[])

    # rglob() follows symlinked subdirectories on this Python version, so a
    # symlink planted inside the workspace (e.g. by a compromised R script)
    # could otherwise surface files from outside it. Keep only entries whose
    # *resolved* real path is still under root (§3.7 — same rule file_content
    # enforces for reads).
    paths = sorted(
        (
            p for p in root.rglob("*")
            if p.is_file()
            and not p.name.startswith(".")
            and p.resolve().is_relative_to(root)
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:_MAX_FILES]

    entries: list[FileEntry] = []
    for p in paths:
        stat = p.stat()
        entries.append(
            FileEntry(
                path=str(p.relative_to(root)),
                size_bytes=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                kind=_kind(p.suffix.lower()),
            )
        )
    return FilesResponse(files=entries)


@router.post("/files", response_model=FileEntry)
async def upload_file(request: Request, file: UploadFile) -> FileEntry:
    """Add a user-chosen local file to the workspace under ``uploads/``.

    Never overwrites: an existing name gets a numbered suffix. The filename is
    reduced to its base name so the client cannot steer the write path.
    """
    data = await read_upload_bounded(file, _MAX_UPLOAD_BYTES)
    name = Path(file.filename or "").name
    if not name or name in {".", ".."} or name.startswith("."):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_FILENAME",
                "message": "ファイル名が不正です。",
                "detail": f"filename={file.filename!r}",
            },
        )

    uploads_dir = _workspace_root(get_services(request)) / _UPLOADS_SUBDIR
    uploads_dir.mkdir(parents=True, exist_ok=True)

    target = uploads_dir / name
    stem, suffix = target.stem, target.suffix
    counter = 1
    while target.exists():
        target = uploads_dir / f"{stem} ({counter}){suffix}"
        counter += 1
    target.write_bytes(data)

    stat = target.stat()
    return FileEntry(
        path=f"{_UPLOADS_SUBDIR}/{target.name}",
        size_bytes=stat.st_size,
        modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        kind=_kind(target.suffix.lower()),
    )


@router.get("/files/content", response_model=None)
async def file_content(
    request: Request, path: str = Query(..., description="Workspace-relative path")
) -> Response | FileContentResponse:
    """Return a single file's text (JSON) or raw image bytes (§3.7).

    Rejects any path escaping the workspace (path traversal).
    """
    root = _workspace_root(get_services(request))
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "PATH_TRAVERSAL",
                "message": "Path escapes the workspace directory.",
                "detail": None,
            },
        )
    if not target.is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "FILE_NOT_FOUND",
                "message": f"No such file: {path}",
                "detail": None,
            },
        )

    suffix = target.suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        media = "image/png" if suffix == ".png" else "image/jpeg"
        return Response(content=target.read_bytes(), media_type=media)

    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > _MAX_PREVIEW_BYTES:
        text = text[:_MAX_PREVIEW_BYTES] + "\n... [truncated] ..."
    language = {
        ".r": "r",
        ".json": "json",
        ".md": "markdown",
        ".csv": "csv",
    }.get(suffix, "text")
    return FileContentResponse(text=text, language=language)
