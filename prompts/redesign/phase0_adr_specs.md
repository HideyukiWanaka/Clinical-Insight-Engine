# CIE 再設計 — Phase 0: 基盤整合・依存追加・足場
# File: prompts/redesign/phase0_adr_specs.md
# Version: 1.0.0

---

## PROMPT R0-0: ブランチ作成

```
git checkout main
git pull origin main
git checkout -b feature/redesign-phase-0-foundation
```

---

## PROMPT R0-1: ADR/spec/MANIFEST の整合と依存追加

```
CIE再設計の基盤を整えます。コードのふるまいは変えず、文書整合と足場のみ作ります。

### 読み込むべき仕様ファイル
- decisions/ADR-0005.md（本再設計の統治決定・4原則）
- spec/api/rest-api-contract.md
- spec/ui/ide-workbench-spec.md
- spec/knowledge/embedding-rag-spec.md
- spec/runtime-workspace-persistence.md
- MANIFEST.yaml / PROJECT_RULES.md（更新対象）

### 実装範囲
- ✅ MANIFEST.yaml の repository 構成に api/ と frontend/ を追記。loading_order に
     decisions/ADR-0005 と新spec群を追加。changelog に v2.3.0 エントリを追加。
- ✅ PROJECT_RULES.md Section 6（hidden state）に脚注を追加し、「.RData 等の可視ファイルは
     hidden state に当たらない（ADR-0005）」を明記。Section 18 の互換性リストに
     「IDE型フロント（API＋Webフロント）」「ローカル埋め込みRAG」を追加。
- ✅ schemas/knowledge-entry.schema.json に embedding フィールド（任意）を追加。
- ✅ pyproject.toml に optional extra `rag`（例: onnxruntime, ベクトル演算用の numpy 等）と
     `api`（fastapi, uvicorn, python-multipart, websockets）を追加。既存 deps は変更しない。
- ✅ 空ディレクトリの足場: cie/api/__init__.py, cie/knowledge/embedding_index.py（stub）,
     frontend/README.md（構成方針のみ）。
- ❌ 実ロジック（API実装・埋め込み実装・フロント実装）は Phase 1 以降。ここでは書かない。

### 踏襲パターン
- MANIFEST/PROJECT_RULES の追記様式は ADR-0003 導入時の差分（v2.2.0 changelog）に倣う。
- schema 追加は analysis-plan.schema.json に analysis_proposal を足した時と同様、
  additionalProperties を壊さず「任意プロパティ」として足す。

### 仕様→実装マッピング（完了基準・全✅で完了）
| 項目 | 反映先 | 状態 |
|------|--------|------|
| api/ frontend/ を構成に追加 | MANIFEST.yaml repository | ⬜ |
| ADR-0005 と新specを loading_order へ | MANIFEST.yaml | ⬜ |
| hidden state 脚注 | PROJECT_RULES.md S.6 | ⬜ |
| embedding フィールド | knowledge-entry.schema.json | ⬜ |
| rag / api extras | pyproject.toml | ⬜ |
| 足場ディレクトリ | cie/api/, cie/knowledge/embedding_index.py, frontend/ | ⬜ |

### 検証（必須）
- `python3 -c "import json,glob; [json.load(open(f)) for f in glob.glob('schemas/*.json')]"` で
  全スキーマがパース可能。
- 既存 pytest が緑（既知のベースライン失敗のみ）を維持: `python3 -m pytest tests/unit -q`。
- MANIFEST.yaml / PROJECT_RULES.md が矛盾なく読める（人手レビュー）。

### ハンドオフ
- 本フェーズ末に「新spec群 + 足場」が揃い、Phase 1 実装者がAPIを書き始められる状態にする。
```
