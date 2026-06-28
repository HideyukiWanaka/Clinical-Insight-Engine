# CIE Platform — Claude Code Implementation Prompts
# Phase 8: Skills Execution Engine & Lifecycle
# File: prompts/phase8_skills.md
# Version: 1.0.0

---

## PROMPT 8-1: Skills ローダーと名前空間解決

```
CIE PlatformのSkillローダーを実装してください。
core/ / meta/ / user/ の3名前空間からSKILL.mdを読み込み、
優先順位（user > core）に従って解決します。

### 読み込むべき仕様ファイル
- decisions/ADR-0002.md (Principle 1〜5、名前空間優先順位)
- spec/skill-lifecycle.md (Section 1: Skill名前空間の定義)
- MANIFEST.yaml (skills.namespaces)

### 前提
- PROMPT 1-1の CIEError が存在します

### 作成するもの

1. `cie/skills/loader.py` を作成してください：

```python
# SkillNamespace Enum:
#   CORE = "core"
#   META = "meta"
#   USER = "user"

# SkillMetadata dataclass:
#   skill_id: str            # 例: "statistics/t-test"
#   namespace: SkillNamespace
#   version: str             # SKILL.mdヘッダから抽出 "# Version: X.Y.Z"
#   skill_path: Path         # SKILL.mdの絶対パス
#   has_examples: bool
#   has_tests: bool
#   has_versions_dir: bool   # core/のみ
#   overrides: str | None    # user/のMETADATA.yamlから (overrides.core_skill_id)

# SkillLoader クラス:
#   NAMESPACE_PRIORITY: list[SkillNamespace] = [
#       SkillNamespace.USER,   # 最優先
#       SkillNamespace.CORE,
#       # META は統計・可視化・レポートSkillとは競合しない
#   ]
#
#   __init__(self, skills_root: Path) -> None
#     - skills_root: プロジェクトルートの skills/ ディレクトリ
#
#   def discover(self) -> dict[str, list[SkillMetadata]]:
#     # skill_id -> 各名前空間でのSkillMetadataリストを返す
#     # 例: {"statistics/t-test": [META_FROM_CORE, META_FROM_USER]}
#     #
#     # 探索パス:
#     #   core:  skills/core/{domain}/{skill_name}/SKILL.md
#     #   meta:  skills/meta/{skill_name}/SKILL.md
#     #   user:  skills/user/{skill_name}/SKILL.md
#     #
#     # SKILL.mdの1行目〜20行目を読み込んでバージョンを抽出
#     #   パターン: "# Version: X.Y.Z" または "# Version: X.Y.Z"
#     # user/のMETADATA.yaml が存在すれば overrides.core_skill_id を読む
#
#   def resolve(self, skill_id: str) -> SkillMetadata:
#     # NAMESPACE_PRIORITY順にskill_idを検索
#     # user/ で見つかればそちらを返す（coreより優先）
#     # どこにも存在しない場合はSkillNotFoundError
#     # meta/ は resolve() の対象外
#     #   （meta SkillはOrchestratorが直接パスを指定して呼ぶ）
#
#   def resolve_meta(self, meta_skill_name: str) -> SkillMetadata:
#     # meta/ 専用のresolver
#     # 例: resolve_meta("skill-evaluator")
#
#   def get_all_core_skills(self) -> list[SkillMetadata]:
#     # core/ の全Skillを返す（Evaluationなどで使用）
#
#   def get_all_user_skills(self) -> list[SkillMetadata]:
#     # user/ の全Skillを返す（REGISTRY.yamlと照合）

# SkillNotFoundError(CIEError) クラス:
#   error_code = "SKILL_NOT_FOUND"
```

2. `cie/skills/registry_manager.py` を作成してください：

```python
# RegistryManager クラス:
#   # skills/user/REGISTRY.yaml の読み書きを管理
#
#   __init__(self, registry_path: Path) -> None
#
#   def load(self) -> dict:
#     # REGISTRY.yamlを読み込みdictで返す
#     # ファイルが存在しない場合は空のregistryを返す（エラーにしない）
#
#   def get_active_skills(self) -> list[dict]:
#     # status="active" のエントリのみ返す
#
#   def register(
#       self,
#       skill_id: str,
#       version: str,
#       overrides_core_skill_id: str | None,
#       audit_event_id: str
#   ) -> None:
#     # REGISTRY.yamlに新エントリを追加
#     # status="active", approved_by="human", registered_at=today
#     # 同一skill_idが既にactiveな場合はSkillAlreadyRegisteredError
#     # 書き込み後にload()で読み直して整合性確認
#
#   def suspend(self, skill_id: str) -> None:
#     # status を "active" -> "suspended" に変更
#
#   def get(self, skill_id: str) -> dict | None:
#     # skill_idに対応するエントリを返す（なければNone）
```

3. `tests/unit/test_skill_loader.py` を作成してください：

```python
# テスト用のtmp_pathにskills/ディレクトリ構造を作成してテスト:
# - test_discover_core_skills: core/の全Skillが検出されること
# - test_discover_user_overrides: user/のSkillがoverridesフィールドを持つこと
# - test_resolve_user_over_core: 同一skill_idではuser/が優先されること
# - test_resolve_meta_separate: meta/はresolve()でなくresolve_meta()で取得
# - test_skill_not_found_error: 存在しないskill_idでSkillNotFoundError
# - test_version_extracted_from_header: SKILL.mdのヘッダからバージョンが抽出されること
# - test_registry_register_and_get: register後にget()で取得できること
# - test_registry_duplicate_active_rejected: 同一skill_idの2重登録でエラー
```

### 制約事項
- SKILL.mdを全文読み込まないこと（ヘッダ20行のみ読めば十分）
- user/ の METADATA.yaml が不正でも SkillLoader がクラッシュしないこと
  （読み込みエラーはlogging.warningとし、該当Skillをスキップ）
- meta/ のSkillは resolve() の返却対象に含めないこと
```

---

## PROMPT 8-2: Skill Lifecycle サービス（評価→提案→承認→更新）

```
CIE PlatformのSkillLifecycleServiceを実装してください。
ADR-0002のPhase 1〜5（評価トリガー→AI提案→Human承認→更新→モニタリング）を実装します。

### 読み込むべき仕様ファイル
- decisions/ADR-0002.md (SkillLifecycleフロー全体)
- spec/skill-lifecycle.md (Section 2〜6)
- spec/permissions.yaml (skill_lifecycle エージェント定義)
- skills/meta/skill-evaluator/SKILL.md
- skills/meta/skill-proposer/SKILL.md

### 前提
- PROMPT 7-3の RegressionChecker が存在します
- PROMPT 8-1の SkillLoader, RegistryManager が存在します
- PROMPT 3-1の CapabilityTokenManager が存在します
- PROMPT 1-3の AuditService が存在します

### 作成するもの

1. `cie/skills/lifecycle.py` を作成してください：

```python
# ProposalStatus Enum:
#   PENDING_HUMAN_REVIEW = "pending_human_review"
#   APPROVED = "approved"
#   REJECTED = "rejected"
#   ARCHIVED = "archived"

# SkillImprovementProposal dataclass:
#   proposal_id: str          # UUID
#   generated_at: datetime
#   target_skill_id: str
#   target_namespace: str     # "core" | "user"
#   current_version: str
#   proposed_version: str
#   trigger_id: str           # "SE-001" | "SE-002" | "SE-003" | "SE-004"
#   trigger_evidence: dict
#   proposed_changes: list[dict]  # spec/skill-lifecycle.md Section 3 準拠
#   human_review_required: bool = True   # 常にTrue (ADR-0002 Principle 4)
#   status: ProposalStatus = ProposalStatus.PENDING_HUMAN_REVIEW

# SkillLifecycleService クラス:
#   __init__(
#       self,
#       skill_loader: SkillLoader,
#       registry_manager: RegistryManager,
#       regression_checker: RegressionChecker,
#       token_manager: CapabilityTokenManager,
#       audit_service: AuditService,
#       db_session_factory: Callable
#   ) -> None
#
#   async def check_and_trigger(
#       self,
#       skill_id: str,
#       skill_namespace: str
#   ) -> list[str]:
#     # RegressionChecker.check_skill_triggers() を呼ぶ
#     # トリガーがあれば audit に SkillEvaluationTriggered を記録
#     # 返却: トリガーIDリスト
#
#   async def generate_proposal(
#       self,
#       skill_id: str,
#       trigger_id: str,
#       trigger_evidence: dict
#   ) -> SkillImprovementProposal:
#     # meta/skill-proposer SKILL.md の手順に従いAI提案を生成
#     # 【重要】ここではSkillファイルを変更しない（提案生成のみ）
#     # proposal をDBに保存（skill_improvement_proposals テーブル）
#     # audit に SkillImprovementProposalGenerated を記録
#     # human_review_required は常にTrue（ADR-0002 Principle 4）
#
#   async def apply_approved_proposal(
#       self,
#       proposal_id: str,
#       capability_token: CapabilityToken,
#       human_decision: dict   # {"action": "approved"|"rejected", "modifications": str}
#   ) -> None:
#     # Step 1: capability_token.require_scope(SKILL_UPDATE_CORE) を検証
#     # Step 2: 提案をDBから取得
#     # Step 3: human_decision.action == "rejected" なら status=REJECTED で終了
#     # Step 4: 承認の場合:
#     #   a. 現在のSKILL.mdを versions/{current_version}/SKILL.md にアーカイブ
#     #   b. 提案内容をSKILL.mdに適用（proposed_changesのdiff形式）
#     #   c. バージョン番号を更新（SKILL.mdヘッダの "# Version:" 行）
#     #   d. status = APPROVED に更新
#     # Step 5: audit に SkillUpdated / SkillProposalReviewedByHuman を記録
#     #
#     # 【制約】ファイル書き込みは全て try/except で囲み、
#     #         失敗時は変更をロールバック（元ファイルを復元）してSkillError送出
#
#   async def register_user_skill(
#       self,
#       skill_id: str,
#       skill_content: str,    # SKILL.mdの全文
#       metadata: dict,        # METADATA.yamlの内容
#       capability_token: CapabilityToken
#   ) -> None:
#     # Step 1: capability_token.require_scope(SKILL_REGISTER_USER)
#     # Step 2: skill_idの形式検証（小文字英数字とハイフン、3〜50文字）
#     # Step 3: 必須セクション確認
#     #   SKILL.mdに "## Overview", "## Procedure", "## Validation Rules",
#     #   "## Tests" が存在すること
#     # Step 4: tests/ に最低1件のテストがあること
#     # Step 5: オーバーライド対象のcore Skillが存在する場合、
#     #         interface互換性をチェック（Applies when セクションが一致）
#     # Step 6: skills/user/{skill_id}/SKILL.md に書き込み
#     # Step 7: METADATA.yamlに approved_by="human", approved_at=today を記録
#     # Step 8: RegistryManager.register() を呼ぶ
#     # Step 9: audit に UserSkillRegistered を記録
```

2. データベーステーブルの追加: `cie/core/database.py` に追記してください：

```python
# 以下のテーブルを database.py に追加:
#
# SkillImprovementProposal テーブル:
#   id: UUID (PK, auto)
#   proposal_id: String(36) (unique)
#   generated_at: DateTime
#   target_skill_id: String(128)
#   target_namespace: String(16)
#   current_version: String(16)
#   proposed_version: String(16)
#   trigger_id: String(8)
#   trigger_evidence: JSON
#   proposed_changes: JSON
#   human_review_required: Boolean (default=True)
#   status: String(32) (default="pending_human_review")
#   human_decision: JSON (nullable)
#   reviewed_at: DateTime (nullable)
```

3. `tests/unit/test_skill_lifecycle.py` を作成してください：

```python
# - test_proposal_always_requires_human: human_review_required は常にTrue
# - test_apply_requires_scope: SKILL_UPDATE_CORE scopeなしでPermissionDeniedError
# - test_archive_before_update: 更新前に versions/ にアーカイブされること
# - test_rollback_on_write_failure: ファイル書き込み失敗で元ファイルが復元されること
# - test_register_user_skill_validates_sections: 必須セクション欠落でSkillError
# - test_register_requires_scope: SKILL_REGISTER_USER scopeなしでPermissionDeniedError
# - test_rejected_proposal_not_applied: rejected提案でファイル変更なし
# - test_skill_id_format_validated: "My_Invalid" のような無効IDでSkillError
```

### 制約事項
- apply_approved_proposal() はhuman_review_required=Trueの提案のみ処理できること
  （Falseに変更されたら拒否）
- ファイル書き込み前に必ずバックアップを作成し、失敗時は復元すること
- register_user_skill() のStep 3〜5をスキップするオプションを作らないこと
```

---

## PROMPT 8-3: User Skill スキャフォールダー

```
CIE Platformのmeta/skill-scaffolderを実装してください。
ユーザーが新しいSkillを追加する際のSKILL.mdテンプレートを生成します。

### 読み込むべき仕様ファイル
- skills/meta/skill-scaffolder/SKILL.md (全手順)
- spec/skill-lifecycle.md (Section 4: User Skill仕様)
- PROJECT_RULES.md Section 11 (User Skillの制約)

### 前提
- PROMPT 8-1の SkillLoader が存在します

### 作成するもの

1. `cie/skills/scaffolder.py` を作成してください：

```python
# ScaffoldResult dataclass:
#   skill_id: str
#   namespace: str   # 常に "user"
#   draft_path: Path
#   files_created: list[str]
#   next_step: str   # "Fill in SKILL.md, then run validation"

# SkillScaffolder クラス:
#   SKILL_ID_PATTERN: re.Pattern = re.compile(r'^[a-z0-9][a-z0-9\-]{2,49}$')
#
#   __init__(
#       self,
#       skills_root: Path,
#       skill_loader: SkillLoader
#   ) -> None
#
#   def scaffold(
#       self,
#       skill_id: str,
#       description: str,
#       overrides_core_skill_id: str | None = None,
#       override_reason: str | None = None
#   ) -> ScaffoldResult:
#     # Step 1: skill_idの形式検証（SKILL_ID_PATTERNに一致しない場合はValueError）
#     # Step 2: オーバーライド対象が存在するか確認
#     #   overrides_core_skill_id が指定された場合:
#     #   skill_loader.resolve(overrides_core_skill_id) で確認
#     #   存在しなければ ValueError("Core Skill not found")
#     # Step 3: draft_path = skills/user/{skill_id}/
#     #   既に存在する場合はValueError("User Skill already exists")
#     # Step 4: SKILL.md を生成
#     #   skills/meta/skill-scaffolder/SKILL.md の Step 3 generate_skill_md に従う
#     #   必須セクション: Overview, Procedure, Validation Rules, Tests
#     #   全セクションに # TODO: プレースホルダーを含める
#     #   オーバーライドの場合: core Skillの "Applies when" と
#     #   "Validation Rules" を継承セクションとして含める
#     # Step 5: METADATA.yaml を生成
#     #   status="draft", approved_at=null, approved_by=null
#     # Step 6: examples/example.md, tests/tests.md を生成（プレースホルダー）
#     # Step 7: ScaffoldResult を返す
#
#   def _generate_skill_md(
#       self,
#       skill_id: str,
#       description: str,
#       overrides_core_skill_id: str | None,
#       override_reason: str | None,
#       core_skill_sections: dict | None   # coreSkillの解析済みセクション
#   ) -> str:
#     # skills/meta/skill-scaffolder/SKILL.md Step 3 に完全準拠
#     # PROJECTルール注記を必ずヘッダに含める:
#     #   "# IMPORTANT: This is a User Skill."
#     #   "# - Must NOT contain project-specific business logic"
#     #   "# - Must NOT access raw patient data"
#     #   "# - Must NOT modify workflow definitions"
#     #   "# - External network access is prohibited"
#
#   def _parse_core_skill_sections(self, skill_md_path: Path) -> dict:
#     # SKILL.mdを読み込み ## セクションをdictで返す
#     # キー: セクション名（例: "Overview", "Validation Rules"）
#     # 値: そのセクションのMarkdown文字列
```

2. `tests/unit/test_scaffolder.py` を作成してください：

```python
# tmp_pathを使ったテスト:
# - test_scaffold_creates_files: 4ファイルが生成されること
#   (SKILL.md, METADATA.yaml, examples/example.md, tests/tests.md)
# - test_invalid_skill_id_rejected: "My_Invalid" でValueError
# - test_nonexistent_override_rejected: 存在しないcoreSkillのオーバーライドでValueError
# - test_existing_skill_rejected: 既存skill_idへの再実行でValueError
# - test_core_validation_rules_inherited: オーバーライド時にValidation Rulesが継承
# - test_project_rules_notice_in_header: ヘッダにIMPORTANT注記が含まれること
# - test_metadata_yaml_status_draft: METADATA.yamlのstatusが"draft"
# - test_todo_placeholders_present: SKILL.mdに# TODOが含まれること
```

### 制約事項
- 生成したSKILL.mdは必ず"## Procedure"セクションを含むこと
- METADATA.yaml の approved_by は null のままにすること
  （"human"への変更はLifecycleService.register_user_skill()が担う）
- テンプレートにビジネスロジックのサンプルコードを含めないこと
  （# TODO: プレースホルダーのみ）
```
