"""In-process store for the latest RStudio environment snapshot (Step 7).

Mirrors ``rstudio.py``'s ``RStudioQueue``: a single in-memory slot for a
single-user, single-process, localhost-bound app (SPEC §4.1). The Addin pushes
a fresh (PII-filtered) snapshot whenever the user's GlobalEnv changes; Step 8
will read ``latest`` to ground chat answers in the real data.
"""

from __future__ import annotations


class EnvironmentStore:
    """Holds the most recent environment snapshot (last-write-wins).

    Not thread-safe by design: single-process, localhost-bound app (SPEC §4.1).
    """

    def __init__(self) -> None:
        self._latest: dict | None = None

    def update(self, snapshot: dict) -> None:
        """Replace the stored snapshot with *snapshot* (already PII-filtered)."""
        self._latest = snapshot

    @property
    def latest(self) -> dict | None:
        """The most recent snapshot, or ``None`` before the first sync."""
        return self._latest


def build_environment_context(snapshot: dict | None) -> str:
    """Render the latest snapshot as a system-prompt section (Step 8).

    Mirrors ``references.build_reference_context``: returns "" when there is no
    environment yet, otherwise a section listing each synced data.frame with its
    real column names, types, missing counts, and group levels — so the model
    grounds method选択 / assumption checks in the user's actual data (SPEC §5.4).
    Aggregates only; no raw row values are ever present here.
    """
    objects = (snapshot or {}).get("objects") or []
    if not objects:
        return ""
    parts = [
        "\n\n# ユーザーのRStudio環境（自動同期・集計のみ）",
        "以下はユーザーが実際にRStudioで読み込んでいるデータの集計情報（列名・型・"
        "欠損数・カテゴリ列の水準と件数）。個々の行データ（セルの値）は含まれない。"
        "手法選択や前提条件の確認では、この実データに基づいて具体的に助言する"
        "（例: 群が3水準なら一元配置分散分析を候補に挙げる／欠損数に触れて除外か"
        "多重代入かを助言する）。コード例では、この実際のオブジェクト名・列名を"
        "そのまま使う。ここに無い列は勝手に仮定しない。",
    ]
    for obj in objects:
        parts.append(
            f"\n## {obj.get('name')}（{obj.get('class')}, {obj.get('nrow')}行）"
        )
        for col in obj.get("columns") or []:
            line = (
                f"- {col.get('name')}: 型 {col.get('type')}, "
                f"欠損 {col.get('n_missing')}"
            )
            levels = col.get("levels")
            if levels:
                rendered = ", ".join(
                    f"{lvl.get('label')}={lvl.get('count')}" for lvl in levels
                )
                line += f", 水準[{rendered}]"
            parts.append(line)
    return "\n".join(parts)
