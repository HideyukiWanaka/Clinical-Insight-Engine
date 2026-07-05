# CIE Platform — REST/WebSocket API 契約
# File: spec/api/rest-api-contract.md
# Version: 1.0.0
# Governs: cie/api/ (新規, FastAPI)
# Basis: ADR-0005 原則1

---

## 1. 目的と原則

新フロント（React IDE）とバックエンドAgentの間の唯一の契約。
PROJECT_RULES.md Section 13「境界を越えるものは必ずスキーマを持つ」に従い、
全ペイロードをここで定義する。

**設計原則:**
- API層は**薄いラッパ**。統計・R実行・匿名化などの業務ロジックを持たない（PROJECT_RULES.md S.4）。
- 各ハンドラは既存の直接呼び出しパターンを踏襲する:
  `token = token_manager.issue(...)` → `AgentInput(...)` → `await agent.run(input)` →
  `finally: token_manager.revoke(token)`（`cie/ui/app.py:593-651` の `_execute_continuation` が原型）。
- サービス群は `cie/api/services.py` に集約（`cie/ui/app.py:59-264` の `_get_services()` を
  移設・共有し、Streamlit UIとAPIの双方から使えるようにする）。
- **束縛アドレスは `127.0.0.1` 固定**（ADR-0005: ローカル漏洩リスク低減）。全リクエストに
  起動時発行のセッショントークン（`X-CIE-Token` ヘッダ）を要求する。

---

## 2. 認証

- 起動時にランダムなセッショントークンを生成し、フロントへ一度だけ受け渡す。
- 全 `/api/*` と `/ws/*` は `X-CIE-Token`（WebSocketは初回メッセージ）で検証。
- 失敗時 `401`。これはネットワーク公開事故時の二重の壁。

---

## 3. RESTエンドポイント

すべて `POST /api/...`（読み取り系のみ `GET`）。リクエスト/レスポンスはJSON。
`execution_id` はサーバ側で `uuid4` 採番して返す。

### 3.1 `POST /api/intent` — 研究意図解析（Planner）
- 呼ぶAgent: `PlannerAgent`（scopes: DATASET_PROXY_METADATA, WORKFLOW_STATE_READ, AUDIT_WRITE_ENTRY）
- req: `{ "prompt": str, "dataset_uploaded": bool }`
- res: `{ "execution_id": str, "intent_object": {...}, "confidence_score": float,
         "requires_human_clarification": bool, "clarification_options": [...] }`
- 備考: データセットは `POST /api/dataset` で先に登録済み前提。列メタデータは
  `_build_dataset_context()`（`cie/ui/app.py:267-347`）を `cie/api/dataset.py` へ移設して生成。

### 3.2 `POST /api/propose` — 会話的なコード提案（Statistics 会話モード）
- 呼ぶAgent: `StatisticsAgent`（`conversational_mode=True`）
- req: `{ "intent_object": {...} }`（初回）または `{ "continuation_query": str,
         "prior_statistical_results": {...}, "prior_r_script": str }`（追加解析）
- res: `{ "execution_id": str,
         "analysis_proposal": { "explanation_markdown": str,
           "code_candidates": [{"candidate_id","label","r_code"}],
           "recommended_candidate_id": str },
         "r_script_provenance": { "llm_generated": bool, "from_cache": bool,
           "knowledge_references": [str], "reason": str|null } }`
- **重要**: `analysis_proposal` が無い（生成失敗）場合も `r_script_provenance.reason` を
  必ず返す。フロントはこれをチャットに表示する（無言失敗の恒久対策）。

### 3.3 `POST /api/run` — Rコード実行（Runtime）
- 呼ぶAgent: `RuntimeAgent`（scopes: RUNTIME_INVOKE_EXECUTION, AUDIT_WRITE_ENTRY）
- req: `{ "r_script": str, "persist_workspace": bool }`
- res: `{ "execution_id": str,
         "execution_result": { "status": str, "exit_code": int, "duration_ms": int,
           "sanitized_stdout_summary": str, "detail": str|null },
         "statistical_results": {...}|null, "statistical_results_reason": str|null,
         "generated_files": [str], "workspace_summary": {...}|null,
         "error_detail": str|null }`
- `persist_workspace=True` の場合、実行ラッパが `.RData` の `load()`/`save.image()` を
  付与する（spec/runtime-workspace-persistence.md 準拠）。executorは無改修（RT-002）。
- **重要**: 失敗時は `error_detail` に `execution_result.detail` /
  `statistical_results_reason` を必ず載せる。

### 3.4 `POST /api/visualize` — 図生成（Visualization）
- 呼ぶAgent: `VisualizationAgent`
- req: `{ "statistical_results": {...}, "intent_object": {...} }`
- res: `{ "execution_id": str, "figures": [{"title","path"}] }`

### 3.5 `POST /api/report` — 原稿生成（Reporting）
- 呼ぶAgent: `ReportingAgent`（scopes: REPORT_COMPILE_MANUSCRIPT, AUDIT_WRITE_ENTRY）
- req: `{ "statistical_results": {...}, "intent_object": {...},
         "reporting_checklist_id": str|null, "target_journal_style": str,
         "reporting_skill_id": str|null }`
- res: `{ "execution_id": str, "manuscript_sections": [{"section_id","text","is_ai_generated"}] }`

### 3.6 `GET /api/files` — ワークスペースのファイル一覧
- req: なし（`workspace_dir` はサーバ設定）
- res: `{ "files": [{"path","size_bytes","modified","kind"}] }`
- 実装は `cie/ui/components/file_browser.py` の走査ロジックを流用。読み取り専用。

### 3.7 `GET /api/files/content?path=...` — 単一ファイルの内容/プレビュー
- res: テキストは `{ "text": str, "language": str }`、画像は `image/png` バイナリ。
- **パストラバーサル禁止**: `path` は `workspace_dir` 配下に正規化・検証してからのみ返す。

### 3.8 知識取り込み（ADR-0003 パイプライン＋ADR-0005 原則4）
- `POST /api/knowledge/ingest` — req: multipart(file)。呼ぶ:
  `KnowledgeIngestionAgent.ingest(file_path, file_bytes, uploaded_by)`。
  取り込み時PIIスキャンで拒否された場合 `422` ＋ `{ "failed_checks": [...] }`。
  res(成功): `{ "draft_id": str, "extracted": {...}, "extraction_limitations": [...] }`
- `POST /api/knowledge/approve` — req: `{ "draft_id": str, "domain": str,
  "trust_level": str, "corrections": {...} }`。呼ぶ:
  `KnowledgeLifecycleService.register_knowledge(...)`。承認後、埋め込み索引を更新（3.9）。
- `POST /api/knowledge/reject` — req: `{ "draft_id": str, "reason": str }`。
- `GET /api/knowledge` — institutional/ の登録済みエントリ一覧（REGISTRY.yaml由来）。

### 3.9 `POST /api/knowledge/reindex` — 埋め込み索引の再構築
- `official/**/*.md` ＋ institutional/ をチャンク化・ベクトル化して索引更新
  （spec/knowledge/embedding-rag-spec.md 準拠、完全ローカル）。
- res: `{ "indexed_docs": int, "chunks": int }`

---

## 4. WebSocket

### 4.1 `WS /ws/console` — Rコンソール出力ストリーム
- クライアントは `execution_id` を購読。サーバは `r_executor` の stdout/stderr を
  **サニタイズ済み**（`ContextGuard.sanitize_stdout`, RT-004）で逐次送信。
- メッセージ: `{ "type": "stdout"|"stderr"|"exit", "text": str, "exit_code": int|null }`
- 生の未サニタイズ出力を送ってはならない。

---

## 5. エラー規約
- `4xx`: クライアント起因（バリデーション・認証・PII拒否）。`{ "error_code", "message", "detail" }`。
- `5xx`: サーバ/Agent内部エラー。`AgentError` / `RuntimeExecutionError` の `error_message` を
  `detail` に載せるが、生データ・PIIは決して含めない。
- **フロントは常に `error_detail`/`reason` を利用者に見せる**（無言失敗を作らない）。

---

## 6. スキーマ整合
- 既存スキーマを流用: `analysis-request.schema.json`（intent）,
  `analysis-plan.schema.json`（propose; `analysis_proposal` 追加済み）,
  `task.schema.json`, `knowledge-entry.schema.json`（`embedding` 追加）。
- API固有のreq/resは `schemas/api/*.schema.json` に追加し、FastAPIの pydantic モデルと対応させる。
