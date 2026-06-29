"""CIE Platform — データプレビュー画面.

アップロード済みCSV/TSV/XLSXデータを表形式で確認するための画面。
生データはAIには送信されない（inject_raw_data_rows=False）が、
人間による確認は問題なく許可されている。
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

_MAX_PREVIEW_ROWS = 100


def render_data_preview(csv_bytes: bytes | None) -> None:
    """アップロード済みデータを表形式でプレビュー表示する。

    Args:
        csv_bytes: `st.session_state["intent_csv_bytes"]` から渡されるバイト列。
                   Noneの場合はアップロード案内を表示する。
    """
    st.title("データプレビュー")

    if csv_bytes is None:
        st.info(
            "データがアップロードされていません。\n\n"
            "「研究意図入力」画面でCSV/TSV/XLSXファイルをアップロードしてください。"
        )
        return

    df, parse_error = _parse_bytes(csv_bytes)

    if parse_error or df is None:
        st.error(f"ファイルの読み込みに失敗しました: {parse_error}")
        return

    total_rows, total_cols = df.shape

    # サマリーメトリクス
    col1, col2, col3 = st.columns(3)
    col1.metric("総行数", f"{total_rows:,} 行")
    col2.metric("列数", f"{total_cols:,} 列")
    col3.metric("ファイルサイズ", f"{len(csv_bytes) / 1024:.1f} KB")

    st.divider()

    # データテーブル（最大100行）
    if total_rows > _MAX_PREVIEW_ROWS:
        st.caption(f"先頭 {_MAX_PREVIEW_ROWS} 行を表示中（全 {total_rows:,} 行）")
    else:
        st.caption(f"全 {total_rows:,} 行を表示")

    st.dataframe(
        df.head(_MAX_PREVIEW_ROWS),
        use_container_width=True,
        hide_index=False,
    )

    # カラム情報（expander）
    with st.expander("▼ カラム情報（データ型）"):
        dtype_df = pd.DataFrame(
            {"カラム名": df.columns, "データ型": df.dtypes.astype(str).values}
        )
        st.dataframe(dtype_df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_bytes(data: bytes) -> tuple[pd.DataFrame | None, str | None]:
    """バイト列をDataFrameにパースする。CSV/TSV/XLSXを自動判定。"""
    # XLSX判定（PK magic bytes）
    if data[:4] == b"PK\x03\x04":
        try:
            return pd.read_excel(io.BytesIO(data)), None
        except Exception as exc:
            return None, str(exc)

    # CSV vs TSV: タブ文字が多ければTSV
    try:
        sample = data[:4096].decode("utf-8", errors="replace")
    except Exception:
        sample = ""

    sep = "\t" if sample.count("\t") > sample.count(",") else ","

    try:
        return pd.read_csv(io.BytesIO(data), sep=sep, encoding="utf-8"), None
    except UnicodeDecodeError:
        pass
    try:
        return pd.read_csv(io.BytesIO(data), sep=sep, encoding="shift_jis"), None
    except Exception as exc:
        return None, str(exc)
