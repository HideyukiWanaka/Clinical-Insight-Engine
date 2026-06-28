# CIE Platform — Claude Code Implementation Prompts
# Phase KIP: Knowledge Ingestion Pipeline
# File: prompts/phase_kip_knowledge_ingestion.md
# Version: 1.0.0
# Reference: decisions/ADR-0003.md (Status: Accepted)
#
# このPhaseはPhase 8（Skills）完了後に実施してください。
# 実施前に必ず以下を読み込んでください：
#   - decisions/ADR-0003.md（全セクション）
#   - MANIFEST.yaml（knowledge.namespaces セクション）
#   - PROJECT_RULES.md（Section 12: Knowledge Rules）

---

## PROMPT KIP-0: ブランチ作成

```
# Phase 8 が main に merge 済みであることを確認してから実行してください。
git checkout main
git pull origin main
git checkout -b feature/kip-knowledge-ingestion
```

---

## PROMPT KIP-1: knowledge/ の3ネームスペース構造移行

```
CIE PlatformのKnowledge Ingestion Pipeline（KIP）の基盤として、
knowledge/ ディレクトリを3ネームスペース構造に移行してください。

### 読み込むべき仕様ファイル
- decisions/ADR-0003.md（原則1: knowledge/ の3ネームスペース構造）
- MANIFEST.yaml（knowledge.namespaces セクション）
- PROJECT_RULES.md（Section 12: Knowledge Rules）

### 前提
- knowledge/ 配下には現在 statistics/, clinical/, reporting/, R/, Python/, visualization/ が存在します

### 実施内容

1. knowledge/ ディレクトリ構造を以下に移行してください：

```
knowledge/
├── official/           ← 既存の全ドメインディレクトリをここに移動
│   ├── statistics/
│   ├── clinical/
│   ├── reporting/
│   ├── R/
│   ├── Python/
│   └── visualization/
├── institutional/      ← 新規作成（空）
│   └── REGISTRY.yaml   ← 知識エントリの台帳（初期は空）
└── pending/            ← 新規作成（空）
    └── .gitkeep
```

2. `knowledge/institutional/REGISTRY.yaml` を作成してください：

```yaml
# knowledge/institutional/REGISTRY.yaml
# CIE Knowledge Ingestion Pipeline — Institutional Knowledge Registry
# ADR-0003: Authoritative list of registered institutional knowledge entries.
# Version: 1.0.0
# 
# Format per entry:
#   entry_id:    KE-XXXX  (zero-padded 4 digits)
#   domain:      statistics | clinical | reporting | R | Python | visualization
#   status:      active | archived
#   trust_level: regulatory | peer_reviewed | institutional | experimental
#   version:     semantic version string
#   created_by:  user identifier
#   approved_by: approver identifier
#   approved_at: ISO-8601 datetime
#   expires_at:  ISO-8601 date | null
#   related_entries: [] or list of {entry_id, relationship}

registry_version: "1.0.0"
entries: []
```

3. 既存コード内で `knowledge/` を直接参照しているパスを更新してください：
   - `knowledge/statistics/` → `knowledge/official/statistics/`
   - `knowledge/clinical/` → `knowledge/official/clinical/`
   - `knowledge/reporting/` → `knowledge/official/reporting/`
   - `knowledge/R/` → `knowledge/official/R/`
   - `knowledge/Python/` → `knowledge/official/Python/`
   - `knowledge/visualization/` → `knowledge/official/visualization/`

   以下のコマンドでパス参照を洗い出してください：
   ```
   grep -r "knowledge/" cie/ agents/ skills/ --include="*.py" --include="*.yaml" --include="*.md" -l
   ```

### 制約事項
- official/ 配下のファイル内容は変更しない（構造移動のみ）
- pending/ には .gitkeep を置き、Gitで追跡できるようにする
- この移行作業はデータベースの変更を伴わない

### テスト
`python3 -c "import pathlib; assert pathlib.Path('knowledge/official/statistics').exists(); assert pathlib.Path('knowledge/institutional/REGISTRY.yaml').exists(); assert pathlib.Path('knowledge/pending/.gitkeep').exists(); print('KIP-1: Directory structure OK')"`
```

---

## PROMPT KIP-2: KnowledgeEntry スキーマとバリデータ

```
CIE PlatformのKnowledge Entry スキーマとPythonバリデータを実装してください。

### 読み込むべき仕様ファイル
- decisions/ADR-0003.md（新規スキーマ定義セクション）
- schemas/knowledge-entry.schema.json（既に MANIFEST.yaml に登録済み）

### 前提
- PROMPT 2-1の SchemaRegistry が存在します（cie/schemas/validator.py）

### 作成するもの

1. `schemas/knowledge-entry.schema.json` を作成してください：

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "knowledge-entry.schema.json",
  "type": "object",
  "required": [
    "entry_id", "domain", "source_info", "knowledge_entries",
    "trust_level", "approved_by_human", "version",
    "status", "created_by", "approved_by", "approved_at"
  ],
  "properties": {
    "entry_id":    { "type": "string", "pattern": "^KE-[0-9]{4}$" },
    "domain": {
      "type": "string",
      "enum": ["statistics", "clinical", "reporting", "R", "Python", "visualization"]
    },
    "version":     { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$" },
    "status": {
      "type": "string",
      "enum": ["active", "archived", "pending"]
    },
    "trust_level": {
      "type": "string",
      "enum": ["regulatory", "peer_reviewed", "institutional", "experimental"]
    },
    "source_info": {
      "type": "object",
      "required": ["title", "year"],
      "anyOf": [
        { "required": ["doi"] },
        { "required": ["url"] }
      ],
      "properties": {
        "title":   { "type": "string" },
        "authors": { "type": "string" },
        "year":    { "type": "integer", "minimum": 1900, "maximum": 2100 },
        "doi":     { "type": "string" },
        "url":     { "type": "string", "format": "uri" },
        "section": { "type": "string" }
      }
    },
    "expires_at": {
      "oneOf": [
        { "type": "string", "format": "date" },
        { "type": "null" }
      ]
    },
    "related_entries": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["entry_id", "relationship"],
        "properties": {
          "entry_id":     { "type": "string", "pattern": "^KE-[0-9]{4}$" },
          "relationship": {
            "type": "string",
            "enum": ["supersedes", "superseded_by", "related"]
          }
        }
      }
    },
    "knowledge_entries": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "statement", "direct_quote"],
        "properties": {
          "id":            { "type": "string" },
          "statement":     { "type": "string", "minLength": 1 },
          "direct_quote":  { "type": "string", "minLength": 1 },
          "confidence":    { "type": "number", "minimum": 0.0, "maximum": 1.0 },
          "caveats":       { "type": "string" }
        }
      }
    },
    "approved_by_human": { "type": "boolean", "const": true },
    "created_by":        { "type": "string" },
    "approved_by":       { "type": "string" },
    "approved_at":       { "type": "string", "format": "date-time" },
    "archived_at":       { "type": ["string", "null"] },
    "archived_by":       { "type": ["string", "null"] }
  }
}
```

2. `cie/knowledge/__init__.py` を作成してください（空パッケージ宣言）

3. `cie/knowledge/models.py` を作成してください：

```python
# KnowledgeDomain Enum:
#   STATISTICS = "statistics"
#   CLINICAL = "clinical"
#   REPORTING = "reporting"
#   R = "R"
#   PYTHON = "Python"
#   VISUALIZATION = "visualization"

# TrustLevel Enum:
#   REGULATORY = "regulatory"       # 規制文書（ICH-E9等）
#   PEER_REVIEWED = "peer_reviewed" # 査読済み論文
#   INSTITUTIONAL = "institutional" # 施設固有の慣行
#   EXPERIMENTAL = "experimental"   # 実験的・暫定的

# KnowledgeStatus Enum:
#   ACTIVE = "active"
#   ARCHIVED = "archived"
#   PENDING = "pending"

# KnowledgeEntryItem dataclass:
#   id: str
#   statement: str              # 知識の主張
#   direct_quote: str           # 原典からの直接引用（根拠）
#   confidence: float = 1.0     # AI確信度 0.0-1.0
#   caveats: str = ""           # 限界・注意事項

# RelatedEntry dataclass:
#   entry_id: str
#   relationship: Literal["supersedes", "superseded_by", "related"]

# SourceInfo dataclass:
#   title: str
#   year: int
#   authors: str | None = None
#   doi: str | None = None
#   url: str | None = None
#   section: str | None = None
#   必須: doi または url のいずれか（両方 None は禁止）

# KnowledgeEntry dataclass:
#   entry_id: str                        # "KE-XXXX"
#   domain: KnowledgeDomain
#   version: str
#   status: KnowledgeStatus
#   trust_level: TrustLevel
#   source_info: SourceInfo
#   knowledge_entries: list[KnowledgeEntryItem]
#   approved_by_human: bool              # const: True（Falseは作成不可）
#   created_by: str
#   approved_by: str
#   approved_at: datetime
#   expires_at: date | None = None
#   related_entries: list[RelatedEntry] = field(default_factory=list)
#   archived_at: datetime | None = None
#   archived_by: str | None = None
#
#   __post_init__ で以下を検証:
#     - approved_by_human must be True（違反時 ValueError）
#     - source_info.doi または source_info.url のいずれかが必須（違反時 ValueError）
#     - entry_id pattern "KE-XXXX"（違反時 ValueError）
```

4. `tests/unit/test_knowledge_models.py` を作成してください：

```python
# テスト項目:
# - test_valid_knowledge_entry_creates: 正常なKnowledgeEntryが作成できる
# - test_approved_by_human_false_raises: approved_by_human=False で ValueError
# - test_source_info_requires_doi_or_url: doi/urlが両方Noneで ValueError
# - test_entry_id_pattern_validated: "KE-ABCD" (非数字) で ValueError
# - test_expires_at_none_allowed: expires_at=None が許可される
# - test_related_entries_default_empty: related_entries がデフォルトで空リスト
```

### 制約事項
- approved_by_human は const: true （False で作成できてはならない）
- source_info は doi または url のいずれかが必須（出典追跡性の担保）
- models.py はビジネスロジックのみ（ファイルI/O・DB操作は含めない）
```

---

## PROMPT KIP-3: IngestionGuard（入口検疫）

```
CIE PlatformのIngestionGuard（ドキュメントアップロード検疫）を実装してください。
アップロードされたドキュメントの安全性を5段階で検証します。

### 読み込むべき仕様ファイル
- decisions/ADR-0003.md（セキュリティ防衛線 Layer 1, 2）
- architecture/security-pii-filter.md

### 前提
- PROMPT 2-2の PIIFilter が存在します（cie/security/pii_detector.py）
- PROMPT KIP-1 の knowledge/ 構造移行が完了しています

### 作成するもの

1. `cie/knowledge/ingestion_guard.py` を作成してください：

```python
# ALLOWED_EXTENSIONS: frozenset = {".pdf", ".md", ".txt", ".docx"}
# MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50MB

# InspectionCheck dataclass:
#   check_name: str
#   passed: bool
#   reason: str
#   sha256: str | None = None  # ファイルハッシュ（重複検出用）

# InspectionResult dataclass:
#   passed: bool                      # 全チェック通過でTrue
#   sha256: str                       # ファイルのSHA-256ハッシュ
#   file_size_bytes: int
#   checks: list[InspectionCheck]
#   failed_checks: list[InspectionCheck]

# IngestionError(CIEError) 例外:
#   error_code: str                   # "FILE_TYPE_NOT_ALLOWED" など
#   failed_checks: list[InspectionCheck]

# IngestionGuard クラス:
#   def __init__(self, known_hashes: set[str] | None = None)
#     # known_hashes: 既にアップロード済みのSHA-256セット（重複検出用）
#
#   def inspect(self, file_path: Path, file_bytes: bytes) -> InspectionResult:
#     # 以下の5段階チェックを実行。1つでも失敗したら IngestionError を送出。
#
#     # Check 1: ファイル拡張子チェック
#     #   file_path.suffix.lower() が ALLOWED_EXTENSIONS に含まれること
#     #   error_code: "FILE_TYPE_NOT_ALLOWED"
#
#     # Check 2: ファイルサイズチェック
#     #   len(file_bytes) <= MAX_FILE_SIZE_BYTES
#     #   error_code: "FILE_TOO_LARGE"
#
#     # Check 3: SHA-256重複チェック
#     #   hashlib.sha256(file_bytes).hexdigest() が known_hashes に含まれないこと
#     #   error_code: "DUPLICATE_DOCUMENT"
#
#     # Check 4: 埋め込みスクリプト検出（PDFのみ）
#     #   拡張子が .pdf の場合、file_bytes の中に b"/JavaScript" または b"/JS" が
#     #   含まれていないことを確認（埋め込みJSによる攻撃ベクトル対策）
#     #   error_code: "EMBEDDED_SCRIPT_DETECTED"
#
#     # Check 5: PII スキャン（テキスト抽出後）
#     #   ファイルをUTF-8デコード（エラー無視）してテキスト化し、
#     #   PIIFilter.run_on_text(text) を呼び出す
#     #   PII発見数 > 0 の場合は error_code: "PII_DETECTED_IN_DOCUMENT"
#     #   ※ PIIFilter に run_on_text() がない場合は簡易実装:
#     #      簡易パターン（数字8桁連続、個人名風パターン等）でチェック
```

2. `tests/unit/test_ingestion_guard.py` を作成してください：

```python
# テスト項目:
# - test_valid_pdf_passes: 正常なPDFバイト列が全チェック通過
# - test_disallowed_extension_fails: .exe ファイルが拒否される
# - test_file_too_large_fails: 51MBのバイト列が拒否される
# - test_duplicate_hash_fails: 同一SHA-256が知識ベースに存在する場合に拒否
# - test_pdf_with_embedded_js_fails: b"/JavaScript" を含むPDFが拒否される
# - test_txt_skips_js_check: .txt ファイルはJSチェックをスキップ
# - test_inspection_result_contains_sha256: 通過時にsha256が返される
# - test_ingestion_error_contains_failed_checks: 失敗時に failed_checks が含まれる
```

### 制約事項
- IngestionGuard は PIIFilter への依存以外の外部ライブラリを使わない
  （hashlib, pathlib は標準ライブラリなので許可）
- PII スキャンの誤検知（false positive）は許容する（安全側に倒す）
- このクラスはファイルシステムへの書き込みを行わない（検疫のみ）
```

---

## PROMPT KIP-4: AbstractDocumentParser と PyMuPDFParser

```
CIE PlatformのドキュメントパーサーをAbstractDocumentParser経由で実装してください。
PyMuPDFへの直接依存を AbstractDocumentParser で完全に隠蔽することが必須要件です。

### 読み込むべき仕様ファイル
- decisions/ADR-0003.md（原則3: AbstractDocumentParser によるライブラリ依存の隠蔽）
- PROJECT_RULES.md（Section 16: "Never depend on a document parser library directly"）

### 前提
- PROMPT KIP-3 の IngestionGuard が存在します

### 作成するもの

1. `cie/knowledge/parsers/__init__.py` を作成してください（空パッケージ宣言）

2. `cie/knowledge/parsers/base.py` を作成してください：

```python
# ParsedDocument dataclass:
#   raw_text: str               # プレーンテキスト抽出結果
#   structured_markdown: str    # Markdown形式の構造化テキスト
#   page_count: int
#   source_hash: str            # SHA-256 of original bytes（再現性確保）
#   parser_name: str            # 例: "pymupdf4llm"（Auditログ用）
#   parser_version: str         # 例: "0.0.17"

# AbstractDocumentParser ABC:
#   @abstractmethod
#   def can_parse(self, suffix: str) -> bool:
#     """このパーサーが処理可能な拡張子かを返す。"""
#
#   @abstractmethod
#   def parse(self, file_path: Path, file_bytes: bytes) -> ParsedDocument:
#     """ファイルをパースして ParsedDocument を返す。
#     
#     実装上の注意:
#       - ライブラリのimportはこのメソッド内でのみ行うこと
#       - パースに失敗した場合は KnowledgeError を送出
#     """
#
#   def get_name(self) -> str:
#     """パーサー名を返す（デフォルト: クラス名）。"""
#     return self.__class__.__name__

# DocumentParserRegistry クラス:
#   def __init__(self, parsers: list[AbstractDocumentParser])
#   
#   def get_parser(self, suffix: str) -> AbstractDocumentParser:
#     """拡張子に対応するパーサーを返す。
#     
#     優先順位: parsers リストの先頭から順に can_parse() を確認。
#     対応パーサーがない場合は KnowledgeError(error_code="NO_PARSER_AVAILABLE")
#     """
```

3. `cie/knowledge/parsers/pymupdf_parser.py` を作成してください：

```python
# PyMuPDFParser(AbstractDocumentParser):
#   """
#   PyMuPDF (AGPL-3.0) の実装クラス。
#   このクラスのみが pymupdf4llm を import する。
#   KnowledgeIngestionAgent は AbstractDocumentParser のみを参照し、
#   このクラス名を直接使用しない。
#   """
#   
#   PARSER_NAME = "pymupdf4llm"
#   PARSER_VERSION = "0.0.17"  # pyproject.toml の pymupdf4llm バージョンと同期
#
#   def can_parse(self, suffix: str) -> bool:
#     return suffix.lower() in {".pdf"}
#
#   def parse(self, file_path: Path, file_bytes: bytes) -> ParsedDocument:
#     # import pymupdf4llm はこのメソッド内のみに局所化
#     # 一時ファイルに書き出してから変換（pymupdf4llmはPathを受け取るため）
#     # 変換後に一時ファイルを削除（finally句で確実に）
#     # ParsedDocument を返す

# PlainTextParser(AbstractDocumentParser):
#   """
#   .md / .txt ファイル用シンプルパーサー（追加ライブラリ不要）。
#   """
#   def can_parse(self, suffix: str) -> bool:
#     return suffix.lower() in {".md", ".txt"}
#
#   def parse(self, file_path: Path, file_bytes: bytes) -> ParsedDocument:
#     # UTF-8デコード（errors="replace"）してそのまま返す
```

4. `tests/unit/test_document_parsers.py` を作成してください：

```python
# テスト項目:
# - test_plain_text_parser_can_parse_md: PlainTextParser が .md を処理できる
# - test_plain_text_parser_can_parse_txt: PlainTextParser が .txt を処理できる
# - test_plain_text_parser_cannot_parse_pdf: PlainTextParser が .pdf を拒否
# - test_plain_text_parser_returns_parsed_document: ParsedDocument が返される
# - test_plain_text_source_hash_consistent: 同一バイト列で同一sha256が返る
# - test_registry_selects_correct_parser: suffixで正しいパーサーが選択される
# - test_registry_raises_for_unknown_suffix: 未対応拡張子で KnowledgeError
# - test_pymupdf_parser_can_parse_pdf: PyMuPDFParser が .pdf を処理できると宣言
#   （実際のPDF変換はintegration testで行うため、ここはcan_parse()のみ確認）

### 制約事項
- AbstractDocumentParser のインターフェースが変わらない限り、
  PyMuPDFParser を他のパーサーに差し替えても KnowledgeIngestionAgent の変更は不要
- pymupdf4llm の import は PyMuPDFParser.parse() 内にのみ存在すること
  （検証コマンド: grep -n "pymupdf" cie/knowledge/ingestion_agent.py → 結果ゼロ）
- pyproject.toml に pymupdf4llm を optional dependency として追加すること
```

---

## PROMPT KIP-5: KnowledgeIngestionAgent

```
CIE PlatformのKnowledgeIngestionAgentを実装してください。
アップロードされたドキュメントから知識を抽出し、
pending/ に KnowledgeEntryDraft を生成します。

### 読み込むべき仕様ファイル
- decisions/ADR-0003.md（KIPフロー Phase 1〜2）
- agents/knowledge-ingestion.yaml（作成が必要）
- MANIFEST.yaml（agents.required に knowledge-ingestion.yaml が登録済み）

### 前提
- PROMPT 5-1の BaseAgent が存在します
- PROMPT KIP-3 の IngestionGuard が存在します
- PROMPT KIP-4 の AbstractDocumentParser / DocumentParserRegistry が存在します

### 作成するもの

1. `agents/knowledge-ingestion.yaml` を作成してください：

```yaml
schema_version: "1.0"
agent_id: "knowledge_ingestion"

metadata:
  name: "Knowledge Ingestion Agent"
  role: "Document parsing, knowledge extraction, and pending entry generation"
  architecture_principles:
    - "AP-009 Verification Before Trust"
    - "ADR-0003 Dynamic Knowledge Ingestion Architecture"

responsibility_boundaries:
  owns:
    - "document_quarantine_via_ingestion_guard"
    - "document_parsing_via_abstract_document_parser"
    - "knowledge_extraction_to_extracted_md"
    - "pending_entry_creation"

  strictly_forbidden:
    - "write_to_knowledge_official"
    - "write_to_knowledge_institutional_without_approval"
    - "execute_code_from_document"
    - "store_patient_data_as_knowledge"
    - "depend_on_document_parser_library_directly"

context_loading:
  inject_raw_data_rows: false

exception_handling:
  on_pii_detected:
    action: "abort_and_report"
    error_code: "PII_DETECTED_IN_DOCUMENT"
  on_parser_failure:
    action: "abort_and_report"
    error_code: "DOCUMENT_PARSE_FAILED"
```

2. `cie/knowledge/ingestion_agent.py` を作成してください：

```python
# KnowledgeEntryDraft dataclass:
#   draft_id: str                 # UUID
#   source_hash: str              # IngestionGuard から取得
#   source_filename: str
#   parsed_text: str              # AbstractDocumentParser の出力
#   extracted_metadata: dict      # LLMが抽出した source_info 候補
#   extracted_knowledge_items: list[dict]  # statement/direct_quote/confidence
#   extracted_trust_level: str    # LLMが推定した trust_level
#   extracted_domain: str         # LLMが推定した domain
#   extraction_limitations: list[str]  # AIが判断できなかった箇所
#   created_at: datetime
#   status: str = "pending_review"

# KnowledgeIngestionAgent クラス:
#   def __init__(
#     self,
#     ingestion_guard: IngestionGuard,
#     parser_registry: DocumentParserRegistry,
#     pending_dir: Path,          # knowledge/pending/
#     source_dir: Path,           # knowledge/institutional/{id}/source/
#   )
#
#   async def ingest(
#     self,
#     file_path: Path,
#     file_bytes: bytes,
#     uploaded_by: str,
#   ) -> KnowledgeEntryDraft:
#     """
#     Phase 1: IngestionGuard.inspect() で検疫
#     Phase 2: DocumentParserRegistry.get_parser() でパース
#     Phase 3: _extract_knowledge() で知識抽出（LLMプロンプト or ルールベース）
#     Phase 4: pending/ に EXTRACTED.md と REVIEW_REQUEST.yaml を保存
#     Phase 5: KnowledgeEntryDraft を返す
#     """
#
#   def _extract_knowledge(self, parsed_doc: ParsedDocument) -> dict:
#     """
#     パース済みテキストから知識エントリの構造を抽出する。
#     LLMを使う場合はここでプロンプトを組み立てる。
#     LLMなしでのルールベース抽出もフォールバックとして実装。
#     戻り値: {
#       "source_info": {...},
#       "domain": "statistics",
#       "trust_level": "peer_reviewed",
#       "knowledge_items": [...],
#       "limitations": [...]
#     }
#     """
#
#   def _save_to_pending(
#     self,
#     draft: KnowledgeEntryDraft,
#     source_bytes: bytes,
#   ) -> Path:
#     """
#     knowledge/pending/{draft_id}/ に以下を保存:
#       - EXTRACTED.md     ← 抽出結果のMarkdown
#       - SOURCE_HASH.txt  ← SHA-256ハッシュ
#       - REVIEW_REQUEST.yaml ← ドラフト情報
#     戻り値: pending ディレクトリのPath
#     """
```

3. `tests/unit/test_ingestion_agent.py` を作成してください：

```python
# テスト項目（モック使用）:
# - test_ingest_valid_txt_creates_draft: 正常なtxtファイルでDraftが作成される
# - test_ingest_invalid_extension_raises: 不正拡張子でIngestionError
# - test_pending_dir_created_on_ingest: pending/ にファイルが作成される
# - test_draft_contains_source_hash: Draftにsha256が含まれる
# - test_ingestion_guard_called_before_parse: IngestionGuardが必ずパース前に呼ばれる
# - test_no_direct_parser_library_import: ingestion_agent.py がパーサーライブラリを直接importしていない

### 制約事項
- KnowledgeIngestionAgent は knowledge/official/ に書き込まない
- KnowledgeIngestionAgent は knowledge/institutional/ に書き込まない
  （institutional/ への書き込みは KIP-6 の KnowledgeLifecycleService のみ）
- _extract_knowledge() の LLM呼び出しはオプション（テスト時はルールベース実装で代替）
```

---

## PROMPT KIP-6: KnowledgeLifecycleService（登録・Soft Delete）

```
CIE PlatformのKnowledgeLifecycleServiceを実装してください。
Human承認後の institutional/ への登録と、論理削除（Soft Delete）を担います。

### 読み込むべき仕様ファイル
- decisions/ADR-0003.md（原則2, 4: 論理削除・Soft Delete / KIPフロー Phase 3-4）
- PROJECT_RULES.md（Section 12: Deletion is Soft Delete only）

### 前提
- PROMPT KIP-2 の KnowledgeEntry / KnowledgeEntryItem モデルが存在します
- PROMPT KIP-5 の KnowledgeEntryDraft が存在します
- PROMPT 1-2の AuditService が存在します

### 作成するもの

1. `cie/knowledge/lifecycle.py` を作成してください：

```python
# KnowledgeRegistrationEvent dataclass（AuditEvent として記録）:
#   event_type = "KnowledgeRegistrationEvent"
#   entry_id: str
#   domain: str
#   approved_by: str
#   trust_level: str

# KnowledgeArchivedEvent dataclass（AuditEvent として記録）:
#   event_type = "KnowledgeArchivedEvent"
#   entry_id: str
#   archived_by: str
#   reason: str

# KnowledgeLifecycleService クラス:
#   def __init__(
#     self,
#     institutional_dir: Path,    # knowledge/institutional/
#     pending_dir: Path,          # knowledge/pending/
#     audit_service: AuditService,
#   )
#
#   def register_knowledge(
#     self,
#     draft: KnowledgeEntryDraft,
#     approved_by: str,
#     domain: str,
#     trust_level: str,
#     source_info: dict,
#     knowledge_items: list[dict],
#     expires_at: date | None = None,
#     related_entries: list[dict] | None = None,
#   ) -> KnowledgeEntry:
#     """Human承認後に institutional/ に登録する唯一のメソッド。
#
#     処理:
#     ① entry_id を採番（KE-XXXX、REGISTRY.yaml の最大番号+1）
#     ② KnowledgeEntry を組み立て（approved_by_human=True 固定）
#     ③ schemas/knowledge-entry.schema.json でバリデーション
#     ④ institutional/{entry_id}/ ディレクトリを作成
#     ⑤ KNOWLEDGE.md を書き込み（Markdown形式）
#     ⑥ METADATA.yaml を書き込み
#     ⑦ source/ ディレクトリを作成し、原典ファイルをコピー
#     ⑧ related_entries がある場合は相手側 METADATA.yaml に逆方向リンクを追記
#     ⑨ REGISTRY.yaml の entries に追記
#     ⑩ pending/ から当該ドラフトを削除
#     ⑪ AuditLog に KnowledgeRegistrationEvent を記録
#     """
#
#   def archive_entry(
#     self,
#     entry_id: str,
#     archived_by: str,
#     current_user_id: str,
#     current_user_role: str,
#     reason: str = "",
#   ) -> None:
#     """論理削除（Soft Delete）。物理削除は絶対に行わない。
#
#     権限チェック:
#       (current_user_id == entry.created_by) OR (current_user_role == "admin")
#       条件不成立 -> PermissionDeniedError(error_code="ARCHIVE_NOT_AUTHORIZED")
#
#     処理:
#     ① METADATA.yaml の status を "archived" に変更
#     ② archived_at / archived_by を記録
#     ③ {entry_id}/ を versions/{entry_id}_{version}_{archived_at}/ に退避
#     ④ REGISTRY.yaml の当該エントリを status: archived に更新
#     ⑤ AuditLog に KnowledgeArchivedEvent を記録
#     ⑥ 物理削除は実装しない（メソッドとして定義しない）
#     """
#
#   def _allocate_entry_id(self) -> str:
#     """REGISTRY.yaml を読み込み、次の KE-XXXX を採番する。"""
#
#   def _update_registry(self, entry: KnowledgeEntry) -> None:
#     """REGISTRY.yaml に entry を追記・更新する（アトミック書き込み）。"""
```

2. `tests/unit/test_knowledge_lifecycle.py` を作成してください：

```python
# テスト項目（tmp_path フィクスチャ使用）:
# - test_register_creates_entry_directory: institutional/{entry_id}/ が作成される
# - test_register_writes_metadata_yaml: METADATA.yaml が正しく書き込まれる
# - test_register_updates_registry: REGISTRY.yaml に新エントリが追記される
# - test_register_entry_id_increments: 2件目は KE-0002 が採番される
# - test_archive_changes_status: status が "archived" に変更される
# - test_archive_unauthorized_user_raises: 権限なしユーザーで PermissionDeniedError
# - test_archive_admin_can_archive_others: admin ロールは他ユーザーのエントリを削除可
# - test_archive_does_not_physically_delete: アーカイブ後もファイルが存在する
# - test_no_physical_delete_method_exists: "delete" を名前に含むメソッドが存在しない

### 制約事項
- archive_entry() は物理削除を行わない
- register_knowledge() 以外のコードパスで institutional/ に書き込まない
- REGISTRY.yaml の書き込みはアトミックに行う
  （一時ファイルへ書き込み→ rename でアトミック置換）
- related_entries の双方向リンク更新は、エラー時にロールバックを試みる
```

---

## PROMPT KIP-7: SystemWorkflowRegistry と Orchestrator統合

```
CIE PlatformのSystemWorkflowRegistryを新設し、
KIPワークフローをOrchestratorと統合してください。

### 読み込むべき仕様ファイル
- decisions/ADR-0003.md（原則5: SystemWorkflowRegistry の新設）
- decisions/ADR-0001.md（Planner責務境界 — Plannerを経由しないことの確認）
- spec/system-workflow.yaml（新規作成対象）

### 前提
- PROMPT 4-1の Orchestrator が存在します（cie/workflow/orchestrator.py）
- PROMPT KIP-5 の KnowledgeIngestionAgent が存在します
- PROMPT KIP-6 の KnowledgeLifecycleService が存在します

### 作成するもの

1. `spec/system-workflow.yaml` を作成してください：

```yaml
schema_version: "1.0"
registry_type: "system"
description: >
  SystemWorkflowRegistry: 管理タスク専用ワークフローの定義。
  Planner Agent を経由せず、UI Event から Orchestrator を直接起動する。
  ADR-0003 に基づき knowledge_ingestion を収容。
  将来の管理タスク（protocol_generation, audit_export 等）もここに追加。

workflows:
  - workflow_id: "knowledge_ingestion"
    description: "Document upload, quarantine, extraction, human review flow."
    trigger: "ui_event.document_upload"
    entry_agent: "knowledge_ingestion"
    stages:
      - stage_id: "quarantine"
        agent_id: "knowledge_ingestion"
        action: "ingest"
      - stage_id: "pending_review"
        agent_id: "reviewer"
        action: "review_knowledge_draft"
        requires_human_approval: true
      - stage_id: "register"
        agent_id: "knowledge_ingestion"
        action: "register_approved"
        condition: "human_approved == true"
    on_rejection:
      action: "delete_pending_draft"
      audit_log: true
```

2. `cie/workflow/system_registry.py` を作成してください：

```python
# SystemWorkflowRegistry クラス:
#   def __init__(self, spec_path: Path)
#     # spec/system-workflow.yaml を読み込む
#
#   def get_workflow(self, workflow_id: str) -> dict:
#     """workflow_id に対応するワークフロー定義を返す。
#     存在しない場合は WorkflowError(error_code="SYSTEM_WORKFLOW_NOT_FOUND")
#     """
#
#   def list_workflow_ids(self) -> list[str]:
#     """登録済みの全 workflow_id を返す。"""
#
# 制約:
#   - このRegistryは Planner Agent から参照されない
#   - Orchestrator が UI Event を受け取った際に直接参照する
#   - AnalysisWorkflowRegistry（既存の WorkflowRegistry）とは独立したクラス
```

3. Orchestrator（`cie/workflow/orchestrator.py`）に以下を追加してください：

```python
# run_system_workflow() メソッドを追加:
#   async def run_system_workflow(
#     self,
#     workflow_id: str,
#     input_data: dict,
#     triggered_by: str,        # UIユーザーID等
#   ) -> dict:
#     """
#     SystemWorkflowRegistry からワークフローを取得して実行。
#     Planner Agent は呼ばない（ADR-0003 原則5）。
#     AuditLog に SystemWorkflowStartedEvent を記録。
#     """
```

4. `tests/unit/test_system_registry.py` を作成してください：

```python
# テスト項目:
# - test_get_knowledge_ingestion_workflow: knowledge_ingestion が取得できる
# - test_unknown_workflow_raises: 存在しない ID で WorkflowError
# - test_list_workflow_ids_returns_all: 全IDのリストが返される
# - test_system_registry_independent_of_analysis_registry:
#     WorkflowRegistry（解析用）と SystemWorkflowRegistry は別インスタンス
# - test_planner_cannot_select_system_workflow:
#     SystemWorkflowRegistry は workflow_selection_rules を持たない（ADR-0001準拠）
```

### 制約事項
- WorkflowRegistry（cie/workflow/registry.py: 解析用）と
  SystemWorkflowRegistry（cie/workflow/system_registry.py: 管理用）は
  必ず別クラス・別ファイルに実装すること
- Planner Agent が SystemWorkflowRegistry を参照するコードパスを実装しない
  （検証: grep -n "system_registry" cie/agents/planner.py → 結果ゼロ）
```

---

## PROMPT KIP-8: FrozenKnowledgeSet と実行時ロード統合

```
CIE PlatformのFrozenKnowledgeSetを実装し、
Orchestratorのワークフロー実行開始時に知識をロードする統合を行ってください。

### 読み込むべき仕様ファイル
- decisions/ADR-0003.md（原則2: official/ の不変性, Layer 5: 実行時 Immutability）
- PROJECT_RULES.md（Section 12: Knowledge is immutable during execution）

### 前提
- PROMPT 4-1の Orchestrator が存在します
- PROMPT KIP-2 の KnowledgeEntry モデルが存在します
- PROMPT KIP-6 の KnowledgeLifecycleService が存在します

### 作成するもの

1. `cie/knowledge/loader.py` を作成してください：

```python
# ExpiryWarning dataclass:
#   entry_id: str
#   level: Literal["expired", "expiring_soon"]
#   message: str

# FrozenKnowledgeSet dataclass（frozen=True）:
#   loaded_at: datetime
#   execution_id: str
#   entries: tuple[KnowledgeEntry, ...]  # immutableタプル
#   expiry_warnings: tuple[ExpiryWarning, ...]
#
#   def get_by_domain(self, domain: KnowledgeDomain) -> tuple[KnowledgeEntry, ...]:
#     """ドメインで絞り込んだエントリを返す（frozen tupleで返す）。"""
#
#   def reload(self) -> None:
#     """実行中の再ロードは禁止。必ず例外を送出する。
#     raise KnowledgeError("KNOWLEDGE_RELOAD_DURING_EXECUTION_FORBIDDEN")
#     """
#
#   ※ dataclass(frozen=True) により、属性への代入は TypeError で拒否される

# KnowledgeLoader クラス:
#   def __init__(
#     self,
#     official_dir: Path,         # knowledge/official/
#     institutional_dir: Path,    # knowledge/institutional/
#   )
#
#   def load_for_execution(self, execution_id: str) -> FrozenKnowledgeSet:
#     """
#     Workflow実行開始時に一度だけ呼ばれる。
#     PROJECT_RULES.md Section 12 の実装。
#
#     処理:
#     ① official/ から全 .md ファイルを読み込み（不変知識）
#     ② institutional/ から status=active のエントリのみを読み込み
#     ③ superseded_by が存在するエントリは新版を優先
#     ④ FrozenKnowledgeSet として返す（実行中は変更不可）
#     """
#
#   def check_expiry_warnings(
#     self,
#     entries: list[KnowledgeEntry],
#   ) -> list[ExpiryWarning]:
#     """
#     UIロード時に呼ばれる（バッチ処理なし）。
#     ADR-0003 原則7: 最小コストUIアラート実装。
#
#     - expires_at < today → level="expired"
#     - expires_at - today <= 90日 → level="expiring_soon"
#     - expires_at is None → スキップ
#     """
```

2. `tests/unit/test_knowledge_loader.py` を作成してください：

```python
# テスト項目:
# - test_load_returns_frozen_set: FrozenKnowledgeSet が返される
# - test_frozen_set_is_immutable: entries への代入が TypeError
# - test_reload_raises_error: reload() が KnowledgeError を送出する
# - test_archived_entries_excluded: status=archived のエントリがロード対象外
# - test_superseded_entry_warning: superseded_by があるエントリに警告が付く
# - test_expired_entry_generates_warning: expires_at が過去日付で "expired" 警告
# - test_expiring_soon_entry_warning: 90日以内で "expiring_soon" 警告
# - test_no_expiry_no_warning: expires_at=None でも警告なし
# - test_get_by_domain_filters_correctly: ドメインで絞り込みが機能する
```

3. Orchestratorの `run_workflow()` 冒頭に KnowledgeLoader の呼び出しを追加してください：

```python
# cie/workflow/orchestrator.py の run_workflow() 冒頭に追加:
frozen_knowledge = self.knowledge_loader.load_for_execution(execution_id)
# frozen_knowledge は DAG 実行中は変更不可
# 各 Agent の context に frozen_knowledge を渡す（読み取り専用）
```

### 制約事項
- FrozenKnowledgeSet は dataclass(frozen=True) で実装すること
- entries は tuple（listではない）で保持すること
- reload() は必ず KnowledgeError を送出すること（テストで確認）
- バッチジョブ・スケジューラは作成しない（UIロード時のオンデマンドチェックのみ）
```

---

## PROMPT KIP-9: Human Review UI（承認・期限切れ警告・関連エントリ）

```
CIE PlatformのKnowledge Human Review UIコンポーネントを実装してください。
研究者がアップロードした知識ドキュメントを審査・承認・却下できる画面を作成します。

### 読み込むべき仕様ファイル
- decisions/ADR-0003.md（KIPフロー Phase 3, 原則6, 7）
- spec/ui/screen-specifications.md（Knowledge管理画面）

### 前提
- Phase 9（UI基盤）が完了しています
- PROMPT KIP-5 の KnowledgeIngestionAgent が存在します
- PROMPT KIP-6 の KnowledgeLifecycleService が存在します
- PROMPT KIP-8 の KnowledgeLoader が存在します

### 作成するもの

1. `cie/ui/components/knowledge_review.py` を作成してください：

```python
# render_knowledge_upload_panel(on_upload: Callable) -> None:
#   """ドキュメントアップロードUI。
#   - st.file_uploader で PDF/MD/TXT/DOCX を受け付ける
#   - アップロード後に on_upload(file_bytes, file_name) を呼ぶ
#   - ビジネスロジックはコールバックに委譲（UIコンポーネント内で Agent を呼ばない）
#   """

# render_knowledge_draft_review(draft: KnowledgeEntryDraft) -> str | None:
#   """抽出済みドラフトのレビューUI。
#   戻り値:
#     "approve" → 承認
#     "reject"  → 却下
#     None      → 判断待ち（まだボタンを押していない）
#
#   表示内容:
#   - 原典情報（タイトル・著者・DOI/URL）
#   - 抽出された knowledge_items（statement + direct_quote + confidence スコア）
#   - confidence < 0.7 のエントリは 🟡 でハイライト
#   - extraction_limitations の一覧
#   - trust_level セレクター（研究者が修正可能）
#   - domain セレクター（研究者が修正可能）
#   - [承認] / [却下] ボタン
#   """

# render_expiry_warnings(warnings: list[ExpiryWarning]) -> None:
#   """有効期限警告バナーUI。
#   ADR-0003 原則7: UIロード時のオンデマンド表示。
#   - level="expired"       → st.error()  で 🔴 表示
#   - level="expiring_soon" → st.warning() で 🟡 表示
#   """

# render_knowledge_registry_panel(
#   entries: list[KnowledgeEntry],
#   current_user_id: str,
#   current_user_role: str,
#   on_archive: Callable[[str], None],
# ) -> None:
#   """institutional/ の登録済み知識一覧UI。
#   - status=active のエントリのみ表示
#   - trust_level 別に 🟢/🔵/🟡/🔴 バッジを表示
#   - superseded_by が存在するエントリに ⚠️「新しいバージョンがあります」を表示
#   - 削除ボタンは (current_user_id == entry.created_by) or role=="admin" のときのみ表示
#   - 削除ボタンクリックで on_archive(entry_id) を呼ぶ
#   """
```

2. `tests/unit/test_knowledge_review_ui.py` を作成してください：

```python
# テスト項目（unittest.mock / st のモック使用）:
# - test_render_expiry_warnings_expired: level=expired でst.error が呼ばれる
# - test_render_expiry_warnings_expiring_soon: level=expiring_soon でst.warning が呼ばれる
# - test_render_expiry_warnings_no_warnings: 空リストで何も呼ばれない
# - test_archive_button_hidden_for_unauthorized: 権限なしユーザーに削除ボタン非表示
# - test_superseded_warning_shown: superseded_by が存在するエントリに警告
# - test_low_confidence_items_highlighted: confidence < 0.7 のエントリに特別表示
```

### 制約事項（Phase 9 UI ルール準拠）
- UIコンポーネント内で KnowledgeIngestionAgent / KnowledgeLifecycleService を
  直接呼ばない（コールバック経由）
- st.session_state への書き込みはapp.py側に集約する
- 削除権限チェックはUIでも行うが、バックエンド（KnowledgeLifecycleService）でも必ず行う
  （UIのみでの権限チェックは禁止）
```

---

## Phase KIP 完了チェックリスト

```
□ knowledge/ の3ネームスペース構造が存在する
  (official/ institutional/ pending/ が全て存在)

□ schemas/knowledge-entry.schema.json が存在し、バリデーションが通る

□ IngestionGuard の5段階チェックが実装されている

□ AbstractDocumentParser を介してのみパーサーライブラリを使用している
  (確認: grep -rn "pymupdf" cie/ | grep -v "pymupdf_parser.py" → 結果ゼロ)

□ KnowledgeIngestionAgent が knowledge/official/ に書き込まない
  (確認: grep -n "official" cie/knowledge/ingestion_agent.py → 書き込みゼロ)

□ KnowledgeLifecycleService.register_knowledge() のみが institutional/ に書き込む

□ archive_entry() が物理削除を行わない
  (確認: "delete" メソッドが KnowledgeLifecycleService に存在しない)

□ SystemWorkflowRegistry が WorkflowRegistry（解析用）とは別クラスで実装されている

□ Planner Agent が SystemWorkflowRegistry を参照しない
  (確認: grep -n "system_registry" cie/agents/planner.py → 結果ゼロ)

□ FrozenKnowledgeSet が dataclass(frozen=True) で実装されている

□ FrozenKnowledgeSet.reload() が KnowledgeError を送出する

□ expires_at の UI警告がバッチ処理なしで実装されている

□ pytest tests/unit/ -k "knowledge or ingestion or kip" が全件パスする

□ decisions/ADR-0003.md の全 Forbidden 項目が実装で守られている
```
