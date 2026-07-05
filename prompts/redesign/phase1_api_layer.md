# CIE 再設計 — Phase 1: FastAPI API層
# File: prompts/redesign/phase1_api_layer.md
# Version: 1.0.0

---

## PROMPT R1-0: ブランチ作成

```
# Phase 0 が main に merge 済みであることを確認
git checkout main && git pull origin main
git checkout -b feature/redesign-phase-1-api
```

---

## PROMPT R1-1: サービスDIの抽出

```
既存Agentを API と Streamlit の双方から使えるよう、サービス組み立てを抽出します。

### 読み込むべき仕様ファイル
- spec/api/rest-api-contract.md（§1 設計原則, §6 スキーマ整合）
- cie/ui/app.py:59-264（_get_services の現行実装＝抽出元）

### 実装範囲
- ✅ cie/api/services.py を新規作成し、_get_services() の中身（各Agent・token_manager・
     schema_registry・audit・reference_library・runtime_agent 等の組み立て）を移設。
     戻り値は同じ dict 構造。
- ✅ cie/ui/app.py の _get_services() は cie/api/services.py の関数を呼ぶだけの薄いラッパにする
     （Streamlit 側の挙動は不変）。
- ❌ 埋め込みRAGへの差し替えはしない（Phase 5）。ここでは既存 MarkdownReferenceLibrary のまま。

### 踏襲パターン
- DIの構造・引数順は現行 _get_services() をそのまま踏襲（cie/ui/app.py:120-227）。

### 検証
- Streamlit が従来通り起動する（PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring を付けて
  `streamlit run cie/ui/app.py --server.headless true` → HTTP 200）。
- pytest 緑を維持。
```

---

## PROMPT R1-2: FastAPIアプリとエンドポイント

```
spec/api/rest-api-contract.md の全エンドポイントを実装します。

### 読み込むべき仕様ファイル
- spec/api/rest-api-contract.md（§2 認証, §3 REST, §4 WebSocket, §5 エラー規約）
- cie/ui/app.py:486-723（_start_continuation_analysis / _execute_continuation ＝踏襲する
  「token発行→AgentInput→agent.run()→finally revoke」の原型）
- cie/agents/base.py:177-252（BaseAgent.run のI/O契約）

### 実装範囲
- ✅ cie/api/main.py: FastAPIアプリ。127.0.0.1束縛、X-CIE-Token検証ミドルウェア、CORSは
     同一オリジンのみ。起動時にセッショントークン生成。
- ✅ cie/api/routes/ に各エンドポイント（intent, propose, run, visualize, report, files,
     knowledge_*）。各ハンドラは services.py のAgentを直接呼び出しパターンで実行。
- ✅ WS /ws/console: r_executor の stdout/stderr を ContextGuard.sanitize_stdout 済みで配信。
- ✅ req/res の pydantic モデルを cie/api/models.py に定義（schemas/ と対応）。
- ✅ 失敗時 error_detail / r_script_provenance.reason を必ずレスポンスに載せる（無言失敗禁止）。
- ❌ フロントは作らない（Phase 2）。curl/httpx で叩ける状態がゴール。

### 踏襲パターン（重要・file:line）
各ハンドラの骨子は _execute_continuation（cie/ui/app.py:593-651）と同一:
```python
token = services["token_manager"].issue(
    execution_id=execution_id, agent_id="runtime", step_id="api_run",
    requested_scopes={CapabilityScope.RUNTIME_INVOKE_EXECUTION,
                      CapabilityScope.AUDIT_WRITE_ENTRY})
try:
    agent_input = AgentInput(execution_id=..., node_id="api_run",
        capability_token=token, payload={...},
        input_schema_ref="cie://schemas/task-context.schema.json")
    output = await services["runtime_agent"].run(agent_input)
finally:
    services["token_manager"].revoke(token)
```
（`asyncio.run` はFastAPIでは不要。ハンドラを async にして `await agent.run(...)`。）

### ハーネス雛形（実データE2E）
```python
# scratchpad/harness_api_smoke.py — Phase 1 用
# 1. dataset を /api/dataset に投入（sample_data.csv）
# 2. /api/intent → intent_object を得る
# 3. /api/propose → analysis_proposal（LLMスタブ可）を得る
# 4. /api/run に固定Rコード（print(1+1)）を送り execution_result を得る
# 5. WS /ws/console に接続し stdout ストリームを受ける
# 6. 各レスポンスに execution_id と（失敗時）error_detail/reason があることを assert
```

### 仕様→実装マッピング（完了基準）
| API | ハンドラ | 呼ぶAgent | 状態 |
|-----|---------|-----------|------|
| POST /api/intent | routes/intent.py | PlannerAgent | ⬜ |
| POST /api/propose | routes/propose.py | StatisticsAgent(conversational) | ⬜ |
| POST /api/run | routes/run.py | RuntimeAgent | ⬜ |
| POST /api/visualize | routes/visualize.py | VisualizationAgent | ⬜ |
| POST /api/report | routes/report.py | ReportingAgent | ⬜ |
| GET /api/files(/content) | routes/files.py | (file_browser流用) | ⬜ |
| /api/knowledge/* | routes/knowledge.py | Ingestion/Lifecycle | ⬜ |
| WS /ws/console | routes/ws_console.py | r_executor stream | ⬜ |

### 検証（必須）
- uvicorn で起動し、harness_api_smoke.py が全 assert を通る。
- tests/integration/test_api_*.py を追加（TestClient で各エンドポイントの契約を検証）。
- pytest 緑を維持。無認証リクエストが 401 になることを確認。
```
