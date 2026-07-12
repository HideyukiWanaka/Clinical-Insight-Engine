# 統計Skillの追加ガイド（新しい解析パターンをカタログに載せる）

**対象:** `skills/core/statistics/` または `skills/user/` に統計手法のSkillを追加する開発者・施設管理者
**関連:** ADR-0002（Skill 3名前空間）, `spec/skill-lifecycle.md`（承認プロセス）,
`cie/agents/statistics.py`（手法カタログ）, `cie/skills/loader.py`（Skill探索）

---

## なぜSkillを追加するのか

CIEのRコード生成はLLMベースで、Skillは「検証済みの手順」を**根拠(grounding)**として
プロンプトに注入する役割を持つ。Skillが無い手法は「カタログ外(off-catalogue)」として
生成は続行されるが、チャットに⚠️警告が出て、統計的妥当性の保証（前提条件・引数・効果量の扱い）が
弱くなる。**新しい手法をSkill化して `_METHODS`/`_METHOD_TO_SKILL_ID` に配線すると、その手法は
カタログ内になり、off_catalog 警告が自動的に消える。**

判定ロジックは `cie/agents/statistics.py::StatisticsAgent._select_method`（`objective` が
モデル化済みか）と `_skill_grounding`（Skillブロックの有無）。

---

## 1. 配置とディレクトリ構造

| 名前空間 | 置き場所 | 探索条件 | 承認 |
|---------|---------|---------|------|
| core（公式） | `skills/core/<domain>/<skill-name>/SKILL.md` | `SkillLoader.discover()` が `core/{domain}/{name}/SKILL.md`（**3階層ちょうど**）を拾う | SkillLifecycle＋人間承認（ADR-0002） |
| user（施設固有） | `skills/user/<skill-name>/SKILL.md` ＋ `METADATA.yaml` | `discover()` が `user/*/SKILL.md` を拾う | 人間承認＋ `skills/user/REGISTRY.yaml` 登録 |

```
skills/core/statistics/<skill-name>/
├── SKILL.md          # 必須（下記テンプレ）
├── examples/         # 入出力例（ADR-0002 structure_per_skill）
├── tests/            # 手順の検証テスト
└── versions/         # 旧版アーカイブ（core のみ）
```

**必須:** SKILL.md の先頭20行以内に `# Version: X.Y.Z` 行を置く
（`SkillLoader._extract_version` が正規表現 `#\s*Version:\s*(\S+)` で読む。無いと `0.0.0` 扱い）。

---

## 2. SKILL.md テンプレート

既存の `skills/core/statistics/t-test/SKILL.md` を範として、以下の構成にする。

```markdown
# SKILL: <人間可読名（例: One-Way ANOVA with Welch correction）>
# Skill ID: statistics/<skill-name>
# Version: 1.0.0
# Consumers: statistics agent
# Knowledge references:
#   - knowledge/official/statistics/<根拠ドキュメント>.md   # 出典（必須：根拠追跡）

## Overview
<この手順が何をするか。1〜3文。>

## Applies when
- `intent_object.objective ∈ {<該当objective>}`
- `intent_object.outcome_type = <continuous | categorical_* | survival>`
- `intent_object.predictor_type = <...>` / n_groups 等の条件

## Procedure

### Step 1 — 入力検証とデータ読込
```r
# データ読込は必ずこの形（BOM・多バイトヘッダ対策）
data <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"), "dataset.csv"),
                 stringsAsFactors = FALSE,
                 check.names = FALSE, fileEncoding = "UTF-8")
outcome_var <- "<解決済みの実列名>"   # var_n ではなく実名を使う
group_var   <- "<実列名>"
stopifnot(outcome_var %in% names(data))
```

### Step 2 — 前提条件チェック
<正規性・等分散・独立性・サンプルサイズ等。違反時の分岐（例: 非正規→ノンパラ）。>

### Step 3 — 検定/推定の実行
<主たる関数と正しい引数。非base パッケージは requireNamespace ガード＋base-R代替。>

### Step 4 — 効果量
<名称付きの効果量と算出式、解釈基準（small/medium/large）。>

### Step 5 — result.json 出力（downstream 必須キー）
```r
# OUTPUT_DIR/result.json に以下のキーで書く（下流エージェントが読む）
#   method_id, test_name, test_statistic, df, p_value, effect_size,
#   effect_size_measure, ci_lower, ci_upper, sample_size, group_summaries
```

## Validation Rules
- `p_value` は (0,1)
- `effect_size` は ≥ 0
- CI が NA のとき（例: タイのあるWilcoxon）は `ci_note` を必ず設定
- `p_value < 0.05` かつ CI が算出可能なら CI は 0 を含まない
- 手法固有の不変条件（例: paired なら n_pairs = min(n_per_group)）
```

> 補足: 非base パッケージ（jsonlite/car/dplyr 等）は必ず
> `requireNamespace("<pkg>", quietly = TRUE)` でガードし、未導入時の base-R 代替を書く
> （`cie/agents/statistics.py` の生成プロンプト方針と一致。未導入パッケージで解析を中断させない）。

---

## 3. コードへの配線（`cie/agents/statistics.py`）

Skillファイルを置くだけでは手法カタログには載らない。以下を追加する。

1. **`_METHODS`** に手法エントリ:
   ```python
   "<method_id>": {
       "method_id": "<method_id>",
       "name": "<表示名>",
       "r_function": "<主関数>",
       "r_packages": ["base"],            # 非baseは requireNamespace 前提
       "assumption": "normal|non_parametric",
       "effect_size_measure": "<名称>",
       "effect_size_benchmark": "Small=..., Medium=..., Large=...",
       "justification_template": "<選択理由テンプレ>",
   },
   ```
2. **`_METHOD_TO_SKILL_ID`** に対応付け: `"<method_id>": "statistics/<skill-name>"`。
3. **`_select_method`** に分岐を追加し、その `objective` が **モデル化済み** として `matched=True` を
   返すようにする（`_CATALOG_OBJECTIVES` / `_GROUP_COMPARISON_OBJECTIVES` の更新、または新分岐）。
   ここまで済むと当該手法は off_catalog にならない。
4. 必要なら **`_ASSUMPTION_CHECKS_BY_METHOD`** に前提チェックを追加。
5. （任意）**`_METHOD_ALTERNATIVES`** に非パラ代替を登録すると、会話型提案が
   「主手法＋代替」の2候補を出す。

---

## 4. 承認プロセス（ADR-0002 / spec/skill-lifecycle.md）

- **core/**: `skills/core/` の変更は SkillLifecycle プロセス＋人間承認が必須。旧版は
  `versions/` にアーカイブ。
- **user/**: `skills/user/<name>/` ＋ `METADATA.yaml`（`overrides.core_skill_id` で core を上書き可）
  を追加し、`skills/user/REGISTRY.yaml` に登録＋人間承認。優先度は user/ > core/。
- Skillは実行可能コードを「知識」として持つが、患者データのハードコード・ワークフロー定義の変更・
  セキュリティ回避・外部ネットワークアクセスを**含めてはならない**（PROJECT_RULES §11）。

---

## 5. 追加後の確認

- `SkillLoader.discover()` に新Skillが現れる（`skill_id = "statistics/<skill-name>"`）。
- 該当 `objective` の解析で `r_script_provenance.off_catalog == false` かつ
  `grounded_by_skill == true`（チャットの⚠️バナーが消える）。
- 生成Rが `result.json` を必須キーで出力し、R環境（car/dplyr/jsonlite 導入済み）で実行成功する。
