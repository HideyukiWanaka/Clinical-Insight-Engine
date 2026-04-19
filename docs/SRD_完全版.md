# System Requirements Document (SRD) — 完全版
# Clinical Insight Engine (CIE) v1.0

**作成日**: 2026-04-18  
**ステータス**: 確定（実装開始可）  
**元仕様書**: `仕様書`（2026-04-17 作成）+ 設計会話（2026-04-18）を統合

> **Role of AI Agent**: You are an Expert Full-Stack Developer and Data Engineer.  
> Your task is to build the CIE application strictly following ALL specifications defined below.  
> Do NOT make assumptions outside of this document. Every ambiguity has been resolved.

---

## 1. System Architecture & Tech Stack

### Frontend
- **Framework**: Next.js (App Router), TypeScript
- **Styling**: TailwindCSS
- **State Management**: Zustand
- **Authentication**: NextAuth.js（Google OAuth 2.0 のみ）
- **対応デバイス**: PC専用（v1）。コンポーネントはレスポンシブ対応可能な設計とし、v2でモバイル対応に昇格できるようにすること

### Backend
- **Language**: Python 3.11+
- **Framework**: FastAPI（REST API、Uvicorn）

### Statistical Engine
- **Environment**: Dockerized R（完全隔離コンテナ）
- **API**: Plumber（HTTP REST API）
- **Security**: コンテナはインターネットアクセスを持たない（`--no-internet`）
- **Communication**: FastAPIバックエンドからHTTP経由でのみ呼び出す

### AI Service
- **Provider**: Anthropic Claude API（最新のマルチモーダルモデル）
- **用途**: 欠損値処理コード生成 / Visual Reference（画像→Rコード）
- **セキュリティ制約**: 生データ行は送信禁止。列名・型・欠損率のメタデータのみ送信

### Integrations
- Google Workspace API（Slides / Docs / Drive）
- OAuth 2.0（NextAuth.js経由）

### Database
- **RDBMS**: PostgreSQL
- **Migration**: Alembic
- **用途**: ユーザープロファイル、ワークフロー定義、テンプレートマッピング、監査ログ

### Ephemeral Storage
- **Technology**: Redis（TTL付き）
- **用途**: アクティブセッション中の臨床データ（CSV生データ本体）
- **ライフサイクル**: ワークフロー実行完了またはセッションタイムアウト時に即時削除。TTLは最大24時間

### 開発・起動環境
- **方式**: Docker Compose（ローカルMac上での起動）
- **サービス構成**: frontend / backend / r-engine / postgres / redis

---

## 2. Core Data Models（TypeScript Interface）

```typescript
// ======================================================
// 1. ワークフロー定義
// ======================================================
interface Workflow {
  id: string;
  userId: string;
  name: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  createdAt: Date;
  updatedAt: Date;
}

interface WorkflowNode {
  id: string;
  type: 'INPUT' | 'CLEAN' | 'ANALYZE' | 'VISUALIZE' | 'OUTPUT';
  skillId?: string;
  // CLEANノードの場合: userInstruction（自然言語）とgeneratedRCode（承認済みRコード）を含む
  parameters: Record<string, any>;
  positionOrder: number; // ステップウィザードでの順序
}

interface WorkflowEdge {
  id: string;
  sourceNodeId: string;
  targetNodeId: string;
}

// ======================================================
// 2. テンプレートマッピング定義
// ======================================================
interface TemplateMapping {
  templateId: string;
  googleDriveFileId: string;
  fileType: 'SLIDES' | 'DOCS'; // Google Slides または Google Docs
  tags: Array<{
    placeholder: string; // 例: "{{age_mean}}" または "{{km_curve_1}}"
    type: 'TEXT' | 'IMAGE' | 'TABLE';
    dataSourceNodeId: string;
  }>;
}

// ======================================================
// 3. Visual Reference ペイロード
// ======================================================
interface VisualReferencePayload {
  referenceImageBase64: string;
  targetVariables: {
    x?: string;
    y?: string;
    group?: string;
    [key: string]: string | undefined;
  };
  userAdditionalInstruction?: string; // ユーザーが追加で指示できる自然言語フィールド
  outputFormat: 'PNG' | 'TIFF';
  outputDpi: 300 | 600;
}

// ======================================================
// 4. CLEANノード パラメータ
// ======================================================
interface CleanNodeParameters {
  userInstruction: string;        // 自然言語指示文（必須、デフォルトなし）
  generatedRCode: string;         // Claude生成 + ユーザー承認済みRコード
  generatedAt: Date;              // コード生成日時
  columnMetadataSent: ColumnMeta[]; // Claudeに送信したメタデータ（監査用）
  randomSeed?: number;            // miceなど乱数使用時に自動挿入
}

interface ColumnMeta {
  name: string;           // 列名（日本語可）
  type: 'numeric' | 'factor' | 'date' | 'character';
  missingCount: number;
  missingRate: number;    // 0.0 〜 1.0
}

// ======================================================
// 5. データセッション（Redis保存内容）
// ======================================================
interface DataSession {
  sessionId: string;
  userId: string;
  workflowId: string;
  rawDataKey: string;     // Redisキー（AES暗号化）
  columnMetadata: ColumnMeta[];
  uploadedAt: Date;
  ttlSeconds: number;     // 最大86400（24h）
}
```

---

## 3. Analysis Skills 一覧（v1 実装対象、全11種）

各スキルは `r-engine/skills/{skill_id}.R` として独立したファイルで実装する。  
新スキルはファイルを追加するだけで拡張可能な構成とすること（Plumberルーターを自動スキャン）。

| skill_id | スキル名 | Rパッケージ | 主な用途 |
|----------|---------|-----------|---------| 
| `table1_generator` | 記述統計表（Table 1） | `tableone`, `finalfit` | ベースライン特性表・群間比較 |
| `chi_square_fisher` | χ²検定 / Fisher正確検定 | `stats` | カテゴリ変数の群間比較 |
| `ttest_mannwhitney` | t検定 / Mann-Whitney U検定 | `stats` | 連続変数の群間比較 |
| `normality_check` | 正規性検定 + 分布確認 | `stats`, `ggplot2` | Shapiro-Wilk / Q-Qプロット / ヒストグラム |
| `logistic_regression` | ロジスティック回帰 | `stats`, `finalfit` | 二値アウトカムの多変量解析 |
| `linear_regression` | 線形回帰 | `stats` | 連続アウトカムの多変量解析 |
| `kaplan_meier` | Kaplan-Meier曲線 + Log-rank検定 | `survival`, `survminer` | 生存時間の記述・群間比較 |
| `cox_regression` | Cox比例ハザード回帰 | `survival`, `finalfit` | 生存時間の多変量解析 |
| `correlation_analysis` | 相関分析（Pearson / Spearman） | `stats`, `ggplot2` | 連続変数間の相関 |
| `roc_auc` | ROC曲線・AUC | `pROC` | 診断能・予測能の評価 |
| `forest_plot` | フォレストプロット | `forestplot`, `ggplot2` | メタ解析・サブグループ解析 |
| `sample_size_calc` | サンプルサイズ計算 | `pwr`, `WebPower`, `powerSurvEpi` | 検出力計算（検定手法はユーザー選択） |

---

## 4. Feature 1: データ入力・前処理パイプライン

### 4.1 対応ファイル形式
- CSV（UTF-8 / Shift-JIS / CP932 を自動判定）
- Excel（.xlsx / .xls）

### 4.2 日本語列名
- 列名に日本語（全角・ひらがな・カタカナ）を含む場合も正常に処理すること
- Rコード内では列名をバッククォートで囲む（例: `` df$`年齢` ``）

### 4.3 Excelマルチシート結合
- 複数シートが存在する場合、UIでユーザーが「key変数名」を指定する
- `merge(df1, df2, by="key_variable", all.x=TRUE)` に相当するRコードを生成して記録する
- key変数が一致しない行の扱い（left join）をデフォルトとし、ユーザーが選択可能（全結合も可）

### 4.4 列型推論と型変更
- アップロード直後に列型を自動推論する（numeric / factor / date / character）
- UIで研究者が型を上書きできる
- 変更した型はRコードとして記録する（例: `df$group <- as.factor(df$group)`）

### 4.5 CLEANノード（欠損値処理・変数変換・除外基準）

#### ルール（絶対遵守）
1. **欠損値が1件でも存在する場合、自然言語入力は必須**。入力なしでは次ステップに進めない
2. **デフォルト処理は存在しない**。ユーザーが明示的に指示しなければ処理されない
3. **Claudeへの送信内容は列名・型・欠損率のみ**。生データ行は絶対に送信しない
4. ユーザーが承認したRコードのみをスクリプトに記録する（承認前は記録しない）
5. 欠損値が0件の場合はCLEANノードをスキップ可能（「欠損値なし」をログに記録）

#### Claudeへのシステムプロンプト（固定）
```
You are an expert R data scientist specializing in clinical research.
You will receive:
  - Column metadata: an array of {name, type, missingCount, missingRate}
  - A natural language instruction from the researcher

Generate ONLY executable R code (no markdown, no explanation) that performs
the specified missing value handling on the dataframe `df`.
Rules:
  - Use column names exactly as provided (wrap in backticks if they contain Japanese or spaces)
  - After each exclusion/imputation step, add: cat("[After STEP_NAME] N =", nrow(df), "\n")
  - If random methods (e.g., mice) are used, add: set.seed({AUTO_GENERATED_SEED}) at the top
  - Do NOT fabricate columns or data
  - Do NOT make any assumption beyond the instruction
```

#### 自動生成シード
- `mice` などの乱数を使用するRコードが生成された場合、システムが自動でシード値を決定し `set.seed()` を挿入する
- シード値はワークフローノードに保存される

#### 変数変換
CLEANノード内で以下の変換をサポートする（すべてRコードとして記録）：
- log変換: `df$log_bmi <- log(df$BMI)`
- カテゴリ化: `df$age_grp <- cut(df$age, breaks=..., labels=...)`
- 標準化: `df$age_z <- scale(df$age)`

#### 除外基準の適用
- 除外基準を適用するたびに `cat("[After 条件名] N =", nrow(df), "\n")` を自動挿入
- v1: テキストログとして記録・スクリプトに埋め込む
- v2: CONSORTフローチャート図（`ggconsort` パッケージ）に昇格

---

## 5. Feature 2: Step Wizard UI（ワークフロービルダー）

ワークフローはステップウィザード形式（5ステップ）で実装する。  
v2でドラッグ＆ドロップ形式（React Flow等）に昇格できる設計とすること。

### Step 1: データ確認
- ファイルアップロード
- 列一覧・欠損率・型の表示
- 型の手動変更UI
- マルチシートの場合：key変数の選択

### Step 2: データクリーニング
- 欠損値サマリー（変数名・型・欠損率）の表示
- 自然言語入力フォーム（必須・デフォルトなし）
- 「前回の指示文を引用」ショートカットボタン（定期レポートで特に有用）
- コード生成 → 実行 → プレビュー → 承認のフロー
- 変数変換の設定

### Step 3: 解析実行
- 解析スキル選択（skill_id 11種から複数選択可）
- スキルごとのパラメータ設定フォーム
  - 使用変数の選択（ドロップダウン形式、型フィルタ付き）
  - オプション設定（例：ロジスティック回帰の調整変数）
- 解析実行 → 結果（表・グラフ）をプレビュー
- サンプルサイズ計算（`sample_size_calc`）は研究計画フェーズ用として先頭に配置

### Step 4: 可視化（Visual Reference）
- 参考画像のアップロード（JPEG / PNG）
- Claudeへのリクエスト送信（画像 + targetVariables + userAdditionalInstruction）
- R ggplot2コード生成 → Rコンテナで実行 → グラフプレビュー
- 出力形式の選択: PNG または TIFF、DPI: 300 / 600
- 追加指示の入力（色・フォント・凡例など）と再生成
- 承認後にスクリプトへ記録

#### Claudeへのシステムプロンプト（固定）
```
You are an expert R data scientist. Analyze the attached chart image
(extract chart type, color hex codes, theme, gridlines, legend position).
Generate a completely reproducible R ggplot2 script that mimics this exact design,
using the dataframe `df` and the provided targetVariables.
Additional user instruction: {userAdditionalInstruction}
Output ONLY raw R code, no markdown wrapping.
```

### Step 5: 出力設定
- reproducible_script.R のダウンロード（必須・全ユースケース共通）
- Google テンプレートへの差し込み（任意）
  - Google Drive ファイルID の入力
  - プレースホルダ（`{{variable_name}}`）の自動検出
  - マッピング設定UI（プレースホルダ ↔ WorkflowNodeの結果）
  - 実行 → Googleドライブ上にクローンされたファイルを開く

---

## 6. Feature 3: Template Injection Engine

### 対応テンプレート
- Google Slides（学会発表資料）
- Google Docs（論文・レポート）

### 実行ロジック
1. ユーザーがGoogle Drive上のファイルIDを入力
2. Google API: ファイルをユーザーのDriveにクローン
3. クローンドキュメントを `regex: \{\{[a-zA-Z0-9_]+\}\}` でスキャン
4. UIでプレースホルダ ↔ WorkflowNode結果のマッピングを設定
5. TEXT置換: p値は小数点3桁（例: p=0.043 → "0.043"、p<0.001 → "<0.001"）
6. IMAGE置換: ggplot2が生成したbase64 PNGをSlide/Docに挿入（元の位置・アスペクト比を保持）
7. Google API Rate Limit対策: 指数バックオフ（初回500ms、最大32秒、最大5回リトライ）

---

## 7. Feature 4: 完全再現性の保証（Full Reproducibility）

### 絶対原則
> **CIEで行った全ての解析は、RStudio + raw CSV があれば完全に再現できなければならない**

### Rコードを生成・記録する全操作

| 操作 | 記録タイミング | Rコード例 |
|------|--------------|----------|
| CSVロード | 即時 | `df <- read.csv("raw_data.csv", fileEncoding="UTF-8")` |
| マルチシート結合 | 即時 | `df <- merge(df1, df2, by="patient_id", all.x=TRUE)` |
| 列型変換 | UIで変更時 | `df$group <- as.factor(df$group)` |
| 欠損値処理 | ユーザー承認後 | Claude生成コード（承認済みのみ） |
| 変数変換 | 設定後即時 | `df$log_bmi <- log(df$BMI)` |
| 除外基準適用 | 欠損値処理コードに内包 | `df <- df[!is.na(df$BMI), ]` |
| 各Analysis Skill | 実行後 | skill内の完全なRコード |
| Visual Reference | ユーザー承認後 | Claude生成ggplot2コード（承認済みのみ） |

### reproducible_script.R の完全構造

```r
# ============================================================
# [System] Auto-generated by Clinical Insight Engine
# Date: {CURRENT_DATE}
# Workflow: {WORKFLOW_NAME}
# CIE Version: 1.0
# ============================================================

# ====== 1. Setup & Package Loading ======
# （使用したパッケージのみ自動列挙）
library(tidyverse)
library(survival)
library(finalfit)
library(mice)
library(pROC)
# ...

# ====== 2. Data Loading ======
# ユーザーはCSVファイルをこのスクリプトと同じフォルダに配置すること
df_main     <- read.csv("raw_data_main.csv", fileEncoding = "UTF-8")
df_followup <- read.csv("raw_data_followup.csv", fileEncoding = "UTF-8")

# Merge by key variable: patient_id
df <- merge(df_main, df_followup, by = "patient_id", all.x = TRUE)
cat("[Load] N =", nrow(df), "\n")

# ====== 3. Column Type Conversion ======
df$diagnosis <- as.factor(df$diagnosis)
df$age       <- as.numeric(df$age)
# ...（UIで変更した型のみ自動生成）

# ====== 4. Missing Value Handling ======
# [User Instruction]:
# "BMIの欠損は除外基準として全例除外してください。
#  歩行速度は前後の観察値の平均で補完してください。"
# [Generated by Claude on {DATETIME}]
set.seed(42)  # 乱数を使用する場合のみ自動挿入
cat("[Before cleaning] N =", nrow(df), "\n")
df <- df[!is.na(df$BMI), ]
cat("[After BMI exclusion] N =", nrow(df), "\n")
df$walk_speed <- zoo::na.approx(df$walk_speed, na.rm = FALSE)
cat("[After walk_speed imputation] N =", nrow(df), "\n")

# ====== 5. Variable Transformation ======
df$log_bmi <- log(df$BMI)
df$age_grp <- cut(df$age, breaks = c(0, 65, 75, Inf),
                  labels = c("<65", "65-74", "75+"))

# ====== 6. Exclusion Criteria Summary ======
# 初期 N={N_initial} → 最終解析対象 N={N_final}
df <- df[df$eligible == 1, ]
cat("[Final analysis] N =", nrow(df), "\n")

# ====== 7. Analysis ======

# --- 7.1 Normality Check ---
# {normality_check skill code}

# --- 7.2 Table 1 ---
# {table1_generator skill code}

# --- 7.3 Logistic Regression ---
# {logistic_regression skill code}

# ====== 8. Visualization ======

# --- Figure 1: Kaplan-Meier Curve ---
# [User Reference Image]: figure1_reference.png
# [Generated by Claude on {DATETIME}]
# {visual_reference ggplot2 code}

# ====== 9. Session Information ======
# 再現性保証のため実行環境を記録する
sessionInfo()
```

### LLM生成コードの取り扱い規則
- **承認後のみ記録**: LLMが生成したコードは、Rコンテナで実行確認 → ユーザーが画面上で承認した後にのみ、スクリプトに追記される
- **生成日時を記録**: `# [Generated by Claude on {DATETIME}]` を必ずコメントとして付与
- **自然言語指示を保存**: ユーザーの自然言語指示文も `# [User Instruction]: ...` としてスクリプトに保存
- **承認前コードは揮発**: 未承認のコードはセッション終了時に自動削除

---

## 8. Feature 5: ワークフロー保存・再利用（定期レポート向け）

### 保存内容（PostgreSQL）
- WorkflowNode全定義（パラメータ含む）
- 各CLEANノードの自然言語指示文 + 承認済みRコード
- TemplateMapping定義
- 使用したAnalysis Skillとそのパラメータ

### 再利用フロー（第2期以降）
1. 新期間のCSVをアップロード
2. 欠損値が存在 → 「前回の指示文を引用」ボタンで自然言語指示を読み込み（編集可）
3. 保存済みワークフローを選択して実行
4. 解析が自動実行 → Googleスライドに自動差し込み
5. プレビュー確認 → 承認 → reproducible_script.R をダウンロード（期ごとに命名）

---

## 9. Security & Data Handling（Zero Trust Policy）

| ルール | 詳細 |
|--------|------|
| **Rule 1: データの揮発** | 臨床データ（CSV/Excel）はRedisに暗号化保存（TTL: 24h）。ワークフロー完了またはセッションタイムアウト後に即時 `DEL` |
| **Rule 2: LLMへの送信禁止** | 生データ行はLLM APIに絶対に送信しない。送信するのは列名・型・欠損率のメタデータのみ |
| **Rule 3: R実行環境の隔離** | Rコンテナはインターネットアクセスを持たない。FastAPIバックエンドからのHTTPのみ受け付ける |
| **Rule 4: 認証** | 全エンドポイントはGoogle OAuth 2.0で保護。未認証リクエストは401を返す |
| **Rule 5: 監査ログ** | 全解析実行をaudit_logsテーブルに記録（userId, action, resourceType, timestamp, ipAddress） |

---

## 10. Error Handling & Edge Cases

| エラー種別 | 条件 | レスポンス |
|-----------|------|----------|
| TYPE_MISMATCH | カテゴリ変数が連続変数を要求するスキルにマッピングされた | HTTP 400: `{"error": "TYPE_MISMATCH", "details": "Column '年齢区分' is factor, expected numeric."}` |
| EXECUTION_TIMEOUT | Rスクリプト実行が30秒を超過 | HTTP 408: サブプロセスを終了、メモリ解放後にレスポンス |
| GOOGLE_RATE_LIMIT | Google API Quota Exceeded | 指数バックオフ（初回500ms、最大32秒、最大5回）後にリトライ |
| INVALID_R_CODE | Visual ReferenceまたはCLEANノードでLLMが無効なRコードを生成 | R containerのstderrをエラーメッセージに付加して最大2回自動リトライ |
| MISSING_INSTRUCTION | 欠損値が存在するのに自然言語指示が空 | HTTP 422: 次ステップへの進行をブロック |
| SESSION_EXPIRED | Redisセッションがタイムアウト | HTTP 401: ユーザーにデータ再アップロードを促す |

---

## 11. Database Schema

```sql
-- ユーザー
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       VARCHAR NOT NULL UNIQUE,
    name        VARCHAR NOT NULL,
    google_id   VARCHAR NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ワークフロー
CREATE TABLE workflows (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    name        VARCHAR NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ワークフローノード
CREATE TABLE workflow_nodes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID NOT NULL REFERENCES workflows(id),
    type            VARCHAR NOT NULL CHECK (type IN ('INPUT','CLEAN','ANALYZE','VISUALIZE','OUTPUT')),
    skill_id        VARCHAR,              -- ANALYZE/VISUALIZEノードのみ
    parameters      JSONB NOT NULL,       -- CLEANノードはuserInstruction, generatedRCode等を含む
    position_order  INTEGER NOT NULL
);

-- テンプレートマッピング
CREATE TABLE template_mappings (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL REFERENCES users(id),
    template_name        VARCHAR NOT NULL,
    google_drive_file_id VARCHAR NOT NULL,
    file_type            VARCHAR NOT NULL CHECK (file_type IN ('SLIDES','DOCS')),
    tags                 JSONB NOT NULL    -- プレースホルダとノードIDのマッピング配列
);

-- 監査ログ
CREATE TABLE audit_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id),
    action        VARCHAR NOT NULL,       -- 例: 'WORKFLOW_EXECUTE', 'TEMPLATE_INJECT'
    resource_type VARCHAR NOT NULL,
    resource_id   UUID,
    timestamp     TIMESTAMPTZ DEFAULT NOW(),
    ip_address    INET
);
```

---

## 12. Project Directory Structure

```
clinical-insight-engine/
├── frontend/                          # Next.js App
│   ├── app/
│   │   ├── (auth)/                   # Googleログインページ
│   │   ├── dashboard/                # ダッシュボード（ワークフロー一覧）
│   │   └── workflow/
│   │       └── [id]/
│   │           ├── step1-data/       # データ確認・型設定
│   │           ├── step2-clean/      # 欠損値処理（自然言語入力）
│   │           ├── step3-analyze/    # 解析スキル選択・実行
│   │           ├── step4-visual/     # Visual Reference
│   │           └── step5-output/     # R script出力・テンプレート差し込み
│   ├── components/
│   ├── lib/
│   │   ├── auth.ts                   # NextAuth config (Google OAuth)
│   │   └── api.ts                    # バックエンドAPIクライアント
│   └── stores/                       # Zustand stores
│
├── backend/                          # FastAPI App
│   ├── api/v1/
│   │   ├── data.py                   # データアップロード・CLEANノード
│   │   ├── workflows.py              # ワークフローCRUD
│   │   ├── analysis.py              # 解析スキル実行
│   │   ├── visual_ref.py            # Visual Reference (Claude API)
│   │   ├── templates.py             # Template Injection
│   │   └── export.py                # reproducible_script.R 生成
│   ├── models/                       # SQLAlchemy ORM models
│   ├── services/
│   │   ├── r_client.py              # R engine HTTP client
│   │   ├── llm_client.py            # Claude API client
│   │   └── google_api.py            # Google Workspace client
│   └── core/
│       ├── config.py
│       └── security.py
│
├── r-engine/                         # Dockerized R
│   ├── Dockerfile
│   ├── plumber.R                     # APIルーター（skillsディレクトリを自動スキャン）
│   └── skills/
│       ├── table1_generator.R
│       ├── chi_square_fisher.R
│       ├── ttest_mannwhitney.R
│       ├── normality_check.R
│       ├── logistic_regression.R
│       ├── linear_regression.R
│       ├── kaplan_meier.R
│       ├── cox_regression.R
│       ├── correlation_analysis.R
│       ├── roc_auc.R
│       ├── forest_plot.R
│       └── sample_size_calc.R
│
├── docker-compose.yml                # ローカル開発環境
└── docker-compose.prod.yml           # 本番環境（将来のクラウド移行時に使用）
```

---

## 13. Use Case Workflows（実装時の受け入れ基準）

以下の3ユースケースで End-to-End テストを実施すること。

### UC-1: 臨床研究データ解析 → 論文作成
**成功条件**: 
1. Google OAuth でログインできる
2. CSVをアップロードし、日本語列名が正しく表示される
3. 欠損値処理の自然言語指示が必須フィールドとなっており、空では次ステップに進めない
4. 承認後に生成されたRコードが、自然言語指示文とともにscript.Rに記録されている
5. `reproducible_script.R` をRStudioで実行すると、CIEと全く同じ結果が得られる
6. Google Docs に `{{p_value}}` が数値で置換されている

### UC-2: 臨床研究データ解析 → 学会スライド作成
**成功条件**:
1. Visual Referenceで参考論文のグラフ画像をアップロードし、ggplot2コードが生成される
2. 生成されたグラフがTIFF 300DPIでダウンロードできる
3. Google Slides の指定スライドに画像が挿入されている
4. `reproducible_script.R` にグラフ生成コードが含まれている

### UC-3: 定期レポート提出
**成功条件**:
1. 初回セットアップしたワークフローが保存されている
2. 新期間のCSVをアップロード後、「前回の指示文を引用」ボタンで指示文が復元される
3. 保存済みワークフローを選択して実行し、Google Slidesが自動更新される
4. 期ごとに別名のscript.Rがダウンロードできる

---

## 14. Reproducibility Checklist（実装完了判定基準）

実装完了の判定は以下の全項目をパスすること。

- [ ] CIEを使わずにCSV + script.R だけでRStudioで全く同じ結果が得られる
- [ ] 自然言語指示文がコメントとして script.R に保存されている
- [ ] 全変換ステップでN数のログが `cat()` で出力される
- [ ] 使用したパッケージ・バージョンが `sessionInfo()` に記録される
- [ ] LLM生成コードは「ユーザー承認後のみ」記録される
- [ ] 乱数を使うコード（mice等）では `set.seed()` が自動挿入される
- [ ] 欠損値が存在する場合、指示なしでは次ステップに進めない（UIレベルでブロック）
- [ ] 生データ行がLLM APIに送信されていないことをログで確認できる
- [ ] Rコンテナからインターネットへのアクセスができないことを確認

---

## 15. v2 以降の拡張予定（v1 スコープ外）

| 機能 | 内容 | 対応パッケージ |
|------|------|-------------|
| フローチャート図 | CONSORTフローチャートの自動生成 | `ggconsort` |
| ドラッグ&ドロップUI | Step Wizard → ビジュアルフローエディタ | React Flow |
| チーム機能 | ワークフロー共有・共同編集 | WorkflowにteamId追加 |
| モバイル対応 | レスポンシブUI | TailwindCSS（設計は対応済み） |
| ジャーナルプリセット | 雑誌別の出力フォーマット | 設定ファイルで管理 |
| 感度解析 | 除外基準を変えたサブワークフロー | 既存ワークフローの分岐 |
| クラウドデプロイ | Vercel (Frontend) + Railway/Render (Backend + R Engine) | docker-compose.prod.yml |

---

*このドキュメントは Clinical Insight Engine v1.0 の実装に必要な全要件を網羅しています。*  
*解釈の余地がある記述が発見された場合は、実装着手前にプロダクトオーナーに確認すること。*
