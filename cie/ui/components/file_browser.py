"""CIE Platform — read-only workspace file browser component.

Lists files under the active workspace directory (``dataset.csv``,
``r_scripts/*.R``, ``r_output/*``, ``viz_output/*``) with a lightweight
preview and download button. Presentation only — no writes, no deletes
(matches the platform's security posture: this component only ever reads).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

_MAX_FILES = 200
_PREVIEW_TEXT_SUFFIXES = {".r", ".json", ".txt", ".log"}
_PREVIEW_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_MAX_PREVIEW_BYTES = 20_000


def render_file_browser(workspace_dir: str | None) -> None:
    """Render a read-only listing of files under *workspace_dir*.

    Args:
        workspace_dir: Absolute path to the workspace directory, or None when
            no dataset/execution has happened yet in this session.
    """
    if not workspace_dir:
        st.caption("ワークスペースはまだ作成されていません。データをアップロードすると表示されます。")
        return

    root = Path(workspace_dir)
    if not root.is_dir():
        st.caption(f"ワークスペースディレクトリが見つかりません: `{workspace_dir}`")
        return

    files = sorted(
        (p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:_MAX_FILES]

    if not files:
        st.caption("ワークスペースにファイルがありません。")
        return

    for path in files:
        rel = path.relative_to(root)
        stat = path.stat()
        size_kb = stat.st_size / 1024
        with st.expander(f"📄 {rel}  ({size_kb:.1f} KB)"):
            _render_preview(path)
            try:
                st.download_button(
                    "ダウンロード",
                    data=path.read_bytes(),
                    file_name=path.name,
                    key=f"wb_file_dl_{rel}",
                )
            except OSError:
                st.caption("ダウンロードできません。")


def _render_preview(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix in _PREVIEW_IMAGE_SUFFIXES:
        st.image(str(path))
        return

    if suffix == ".csv":
        try:
            import pandas as pd

            df = pd.read_csv(path, nrows=5)
            st.dataframe(df, use_container_width=True)
        except Exception:
            st.caption("プレビューできません。")
        return

    if suffix in _PREVIEW_TEXT_SUFFIXES:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            st.caption("プレビューできません。")
            return
        truncated = len(text) > _MAX_PREVIEW_BYTES
        if truncated:
            text = text[:_MAX_PREVIEW_BYTES] + "\n... [truncated] ..."
        language = "r" if suffix == ".r" else ("json" if suffix == ".json" else "text")
        st.code(text, language=language)
        return

    st.caption("このファイル形式のプレビューはサポートされていません。")
