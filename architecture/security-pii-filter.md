# PII Detection Filter — Security Architecture
# File: architecture/security-pii-filter.md
# Version: 1.0.0
# Status: Draft
# Parent: architecture/security-model.md
# Architecture Principles: AP-011 Security by Default, AP-012 Offline Capability
# Schema References:
#   - schemas/dataset.schema.json  (ColumnMetadata, SummaryStats, var_n_alias_map)
#   - schemas/analysis-request.schema.json (IntentObject, natural_language_summary)
#   - schemas/agent.schema.json    (ContextLoading.inject_raw_data_rows = const: false)
# Agent References:
#   - agents/security.yaml  (r_code.restore_variables, capability_token lifecycle)
#   - agents/planner.yaml   (PL-004/005/006, context_loading)
#   - agents/data-quality.yaml (DQ-001: no raw data access)
#   - agents/runtime.yaml   (RT-004: sanitized_stdout_summary)

---

## 1. 設計思想

CIE Platformが扱う臨床研究データには、患者氏名・ID・生年月日・電話番号など
個人を特定し得る情報（PII: Personally Identifiable Information）が含まれる可能性がある。

PIIの漏洩リスクは主に2つの経路から発生する。

1. **LLMへの直接注入:** 列名・カテゴリラベル・自由記述がそのままLLMプロンプトに
   渡されることで、モデルの出力やログに患者情報が混入する。

2. **実行ログへの混入:** Rスクリプトのstdout/stderrに患者識別子が出力され、
   監査ログを経由して漏洩する。

CIEのPII保護の核心は**「rawデータをAgentコンテキストに渡さない」**という
設計原則（agent.schema.json `ContextLoading.inject_raw_data_rows = const: false`）であり、
PII検出フィルタはその原則を補強・検証する追加防衛層である。

### 正直なリスク認識

PII検出は完全ではない。正規表現・統計的ヒューリスティック・軽量MLを組み合わせた
多層防御であっても、偽陰性（見逃し）はゼロにはならない。
本フィルタの設計目標は「完全なPII除去の保証」ではなく、
**「Human Authorityとvar_nエイリアス設計と組み合わせることによる大幅なリスク低減」**
である。検出困難なPIIパターン（例: 施設固有のID体系、暗号化されていない自由記述）
については、ユーザーへの明示的な注意喚起と人間によるレビューが最終的な防衛線となる。

---

## 2. 多層防御構造

PII検出フィルタは3つの独立した層で構成される。
各層は独立して動作し、上位層の見落としを下位層が補完する。

```
入力データ（列名 / 値 / 自然言語プロンプト）
         │
    ┌────▼─────────────────────────────────────────┐
    │  Layer 1: 正規表現 + 辞書ベースマッチング    │  決定論的・高速
    │  （日本語姓名、患者ID、生年月日、電話番号）  │  オフライン・依存なし
    └────┬─────────────────────────────────────────┘
         │ Layer 1で未検出のものが通過
    ┌────▼─────────────────────────────────────────┐
    │  Layer 2: 統計的異常検知                     │  ヒューリスティック
    │  （dataset.schema.json の summary_stats      │  オフライン・依存なし
    │    unique_count / inferred_type を活用）     │
    └────┬─────────────────────────────────────────┘
         │ Layer 1+2で未検出のものが通過
    ┌────▼─────────────────────────────────────────┐
    │  Layer 3: 軽量オフラインML（オプション）     │  確率的・高精度
    │  （spaCy日本語NER / 埋め込みベース類似度）   │  モデルが存在する場合のみ
    └────┬─────────────────────────────────────────┘
         │
    ┌────▼──────────────────────┐
    │  検出結果の統合と判定     │
    │  Critical / Warning / OK  │
    └───────────────────────────┘
```

---

## 3. Layer 1 — 正規表現 + 辞書ベースマッチング

### 3.1 適用対象

Layer 1は以下の2種類の入力に適用される。

| 入力種別 | 適用元 | 対象フィールド |
|---------|--------|--------------|
| 列名（オリジナル） | python_utilities.md `extract_structural_metadata()` | `df.columns` |
| カテゴリラベル | dataset.schema.json `SummaryStats.top_categories[].label` | 上位10カテゴリの文字列 |
| 自然言語プロンプト | analysis-request.schema.json `natural_language_summary` | Planner Agent入力前 |

**注:** rawデータの行値そのものは処理しない。
`inject_raw_data_rows = const: false`（agent.schema.json）の設計により、
行値はそもそもAgentコンテキストに渡らない。

### 3.2 検出パターン定義

```python
import re

PII_PATTERNS = {
    # --- 日本語姓名 ---
    "jp_full_name": {
        "pattern": re.compile(
            r"(氏名|患者名|名前|氏　名|患者氏名|受診者名|"
            r"姓名|フルネーム|名前フリガナ|氏名カナ)",
            re.IGNORECASE
        ),
        "severity": "CRITICAL",
        "description": "患者氏名を示す列名パターン"
    },

    # --- 患者・症例ID ---
    "patient_id": {
        "pattern": re.compile(
            r"(患者\s*[Ii][Dd]|patient\s*id|カルテ\s*番号|"
            r"症例\s*[Nn][Oo]|受診\s*者\s*[Ii][Dd]|"
            r"ID番号|識別\s*番号|受付\s*番号|"
            r"\b[Pp]atient[_\s]?[Nn]o\b|\b[Cc]ase[_\s]?[Ii][Dd]\b)",
            re.IGNORECASE
        ),
        "severity": "CRITICAL",
        "description": "患者・症例識別子を示す列名パターン"
    },

    # --- 生年月日・年齢（詳細） ---
    "birth_date": {
        "pattern": re.compile(
            r"(生年月日|誕生日|birth\s*date|dob|date_of_birth|"
            r"生\s*年\s*月\s*日|birthdate|出生年月日)",
            re.IGNORECASE
        ),
        "severity": "CRITICAL",
        "description": "生年月日を示す列名パターン"
    },

    # --- 電話番号 ---
    "phone_number": {
        "pattern": re.compile(
            r"(電話\s*番号|携帯\s*番号|phone|tel\b|telephone|"
            r"連絡先\s*電話|mobile|携帯電話)",
            re.IGNORECASE
        ),
        "severity": "CRITICAL",
        "description": "電話番号を示す列名パターン"
    },

    # --- 住所・郵便番号 ---
    "address": {
        "pattern": re.compile(
            r"(住所|address|郵便\s*番号|postal_code|zip\s*code|"
            r"居住地|在住|自宅)",
            re.IGNORECASE
        ),
        "severity": "CRITICAL",
        "description": "住所・位置情報を示す列名パターン"
    },

    # --- メールアドレス ---
    "email": {
        "pattern": re.compile(
            r"(メール\s*アドレス|email|e-mail|mail\s*address|"
            r"電子メール)",
            re.IGNORECASE
        ),
        "severity": "CRITICAL",
        "description": "メールアドレスを示す列名パターン"
    },

    # --- 医療機関固有ID（日本） ---
    "medical_id_jp": {
        "pattern": re.compile(
            r"(保険\s*証\s*番号|被保険者\s*番号|健康保険\s*番号|"
            r"マイナンバー|個人\s*番号|基礎年金番号)",
            re.IGNORECASE
        ),
        "severity": "CRITICAL",
        "description": "日本の医療・社会保障IDを示す列名パターン"
    },

    # --- カテゴリ値の正規表現（top_categories.label対象）---
    "value_phone_pattern": {
        "pattern": re.compile(
            r"^(\+?81[-\s]?|0)\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4}$"
        ),
        "severity": "CRITICAL",
        "target": "category_label",
        "description": "電話番号形式の値パターン"
    },
    "value_email_pattern": {
        "pattern": re.compile(
            r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
        ),
        "severity": "CRITICAL",
        "target": "category_label",
        "description": "メールアドレス形式の値パターン"
    },

    # --- 警告レベル（要確認・自動マスキング対象）---
    "age_detail": {
        "pattern": re.compile(
            r"(年齢\s*詳細|exact\s*age|正確な年齢|生まれ年|出生年)",
            re.IGNORECASE
        ),
        "severity": "WARNING",
        "description": "詳細な年齢情報を示す列名（5歳階級への粗化を推奨）"
    },
    "free_text": {
        "pattern": re.compile(
            r"(備考|コメント|メモ|自由\s*記載|備考欄|note|comment|"
            r"remarks|free\s*text|その他\s*特記|特記\s*事項)",
            re.IGNORECASE
        ),
        "severity": "WARNING",
        "description": "自由記述欄（氏名等が混入するリスクが高い）"
    },
}
```

### 3.3 検出ロジック（擬似コード）

```python
def layer1_detect(col_name: str, top_categories: list[dict]) -> list[PiiFinding]:
    """
    Layer 1: 列名とカテゴリ値ラベルに対して正規表現マッチングを適用。
    rawデータ行値は引数に含まれない（inject_raw_data_rows=false による設計保証）。
    """
    findings = []

    # 列名に対するマッチング
    for pattern_id, config in PII_PATTERNS.items():
        if config.get("target") == "category_label":
            continue  # 値パターンは後段で処理
        if config["pattern"].search(col_name):
            findings.append(PiiFinding(
                layer=1,
                pattern_id=pattern_id,
                severity=config["severity"],
                target_type="column_name",
                matched_text=col_name,        # 列名は監査ログに記録可能
                description=config["description"]
            ))

    # top_categories.label に対するマッチング（値パターンのみ）
    for cat in top_categories:
        label = cat.get("label", "")
        for pattern_id, config in PII_PATTERNS.items():
            if config.get("target") != "category_label":
                continue
            if config["pattern"].match(label):
                findings.append(PiiFinding(
                    layer=1,
                    pattern_id=pattern_id,
                    severity="CRITICAL",
                    target_type="category_value",
                    matched_text="[REDACTED]",  # 値はログに残さない
                    description=config["description"]
                ))

    return findings
```

---

## 4. Layer 2 — 統計的異常検知

Layer 2はdataset.schema.jsonの`ColumnMetadata`と`SummaryStats`フィールドを
活用して、PIIである可能性が高い統計的特徴を持つ列を検出する。
行値へのアクセスは一切不要であり、Offline Firstと完全に整合する。

### 4.1 検出シグナルと根拠

| シグナル | 使用フィールド | 判定ロジック | 重要度 |
|---------|-------------|------------|--------|
| 識別子疑惑 | `unique_count` / `row_count` | `unique_count / row_count > 0.95` かつ `inferred_type ∈ {text, unknown}` → 主キー系IDの疑い | CRITICAL |
| 自由記述疑惑 | `inferred_type` | `inferred_type = "text"` かつ `unique_count ≈ row_count` | WARNING |
| 日付型カラム | `inferred_type` | `inferred_type = "date"` かつ Layer 1未検出 → 生年月日の可能性 | WARNING |
| 異常に細かい連続値 | `std_dev` / `mean` / `unique_count` | 連続値で `unique_count / row_count > 0.99` → 個人測定値（体重・身長の精密値等）の疑い | WARNING |
| 固定長数字列 | `top_categories[].label` 長さ分布 | 全カテゴリラベルが同一長かつ 8〜12桁数字 → 施設IDや保険番号の疑い | CRITICAL |

### 4.2 検出ロジック（擬似コード）

```python
def layer2_detect(col_meta: ColumnMetadata, row_count: int) -> list[PiiFinding]:
    """
    Layer 2: dataset.schema.json の ColumnMetadata フィールドを用いた
    統計的ヒューリスティック検出。rawデータへのアクセスなし。
    """
    findings = []
    stats = col_meta.get("summary_stats", {})
    unique_count = stats.get("unique_count") or 0
    inferred_type = col_meta.get("inferred_type", "unknown")
    top_cats = stats.get("top_categories", [])

    # シグナル1: 高ユニーク率 × テキスト型 → 識別子疑惑
    if row_count > 0 and inferred_type in ("text", "unknown"):
        uniqueness_ratio = unique_count / row_count
        if uniqueness_ratio > 0.95:
            findings.append(PiiFinding(
                layer=2,
                signal_id="L2-HIGH-UNIQUENESS",
                severity="CRITICAL",
                description=(
                    f"列 {col_meta['var_n']}: ユニーク率 {uniqueness_ratio:.1%}。"
                    "患者IDまたは識別子の可能性があります。"
                ),
                evidence={
                    "unique_count": unique_count,
                    "row_count": row_count,
                    "uniqueness_ratio": uniqueness_ratio,
                    "inferred_type": inferred_type
                }
            ))

    # シグナル2: date型 → 生年月日の可能性
    if inferred_type == "date":
        findings.append(PiiFinding(
            layer=2,
            signal_id="L2-DATE-TYPE",
            severity="WARNING",
            description=(
                f"列 {col_meta['var_n']}: 日付型列を検出。"
                "生年月日など個人特定につながる可能性があります。"
            )
        ))

    # シグナル3: 固定長数字カテゴリ → 保険番号・施設IDの疑い
    if len(top_cats) >= 3:
        label_lengths = [len(c["label"]) for c in top_cats if c["label"].isdigit()]
        if label_lengths and len(set(label_lengths)) == 1 and 8 <= label_lengths[0] <= 12:
            findings.append(PiiFinding(
                layer=2,
                signal_id="L2-FIXED-LENGTH-NUMERIC",
                severity="CRITICAL",
                description=(
                    f"列 {col_meta['var_n']}: {label_lengths[0]}桁の固定長数字。"
                    "保険証番号・施設IDの可能性があります。"
                ),
                evidence={"label_length": label_lengths[0], "sample_count": len(label_lengths)}
            ))

    return findings
```

### 4.3 Layer 2の限界と補足

Layer 2は統計的シグナルに基づくため、以下のケースで偽陰性・偽陽性が生じる。

| ケース | 影響 | 緩和策 |
|--------|------|--------|
| 匿名化済みIDが高ユニーク率 | 偽陽性（CRITICAL誤検出） | Human ReviewでWarning降格可 |
| 患者名が少数カテゴリに集約 | 偽陰性（見落とし） | Layer 1の正規表現で列名を補完 |
| 施設固有の短縮ID体系 | 偽陰性 | Layer 3のNERまたは人間レビューで対応 |

---

## 5. Layer 3 — 軽量オフラインML（オプション）

Layer 3はspaCy日本語NERモデルまたは埋め込みベースの類似度計算を用いた
確率的PII検出層である。外部APIへの依存は一切なく、
Offline First原則（AP-012）と整合する。

**オプション扱いの理由:** モデルファイルのサイズ（50〜300MB）と
推論時間（列ごとに数十ms）が、Desktopアプリケーションのユーザー体験に
影響を与える可能性があるため。ユーザーが明示的に有効化した場合のみ動作する。

### 5.1 spaCy NER（固有表現認識）

適用対象: `top_categories[].label`（カテゴリ値の文字列）

```python
def layer3_ner_detect(top_categories: list[dict]) -> list[PiiFinding]:
    """
    Layer 3a: spaCy 日本語モデルによる固有表現認識。
    モデル: ja_core_news_sm（オフライン）
    対象: top_categories の label 文字列のみ（rawデータ行値ではない）
    """
    try:
        import spacy
        nlp = spacy.load("ja_core_news_sm")
    except (ImportError, OSError):
        return []  # モデル未インストールの場合はスキップ（オプション）

    findings = []
    for cat in top_categories:
        label = cat.get("label", "")
        if len(label) < 2:
            continue

        doc = nlp(label)
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                findings.append(PiiFinding(
                    layer=3,
                    signal_id="L3-NER-PERSON",
                    severity="CRITICAL",
                    description="カテゴリ値に人名の可能性がある固有表現を検出しました。",
                    evidence={
                        "entity_type": ent.label_,
                        "matched_text": "[REDACTED]"  # 値はログに残さない
                    }
                ))

    return findings
```

### 5.2 埋め込みベース列名類似度

適用対象: オリジナル列名。Layer 1の正規表現辞書にない新しいPII列名パターンに対応。

PII既知列名（「患者ID」「氏名」等）の埋め込みベクトルとの
コサイン類似度が閾値（0.85）を超える列名をWARNINGとして検出する。

```python
def layer3_embedding_detect(col_name: str, pii_anchor_embeddings: list) -> list[PiiFinding]:
    """
    Layer 3b: 事前計算済みPIIアンカー埋め込みとのコサイン類似度によるソフトマッチング。
    モデル: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2（オフライン）
    閾値: 0.85（実験的に調整が必要）
    """
    try:
        from sentence_transformers import SentenceTransformer, util
        model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    except ImportError:
        return []

    col_emb = model.encode(col_name, convert_to_tensor=True)
    findings = []
    for anchor in pii_anchor_embeddings:
        sim = util.cos_sim(col_emb, anchor["embedding"]).item()
        if sim > 0.85:
            findings.append(PiiFinding(
                layer=3,
                signal_id="L3-EMBEDDING-SIMILARITY",
                severity="WARNING",
                description=(
                    f"列名 '{col_name}' が既知のPII列名 '{anchor['label']}' と "
                    f"意味的に類似しています（類似度: {sim:.2f}）。"
                ),
                evidence={"similarity": round(sim, 3), "anchor_label": anchor["label"]}
            ))
    return findings
```

---

## 6. 適用タイミング

PII検出フィルタは4つのタイミングで独立して適用される。

```
[適用タイミング1]  ─────────────────────────────────────────────
  Planner Agent 入力前（analysis-request.schema.json生成前）
  
  対象: user_natural_language_prompt
  適用層: Layer 1（プロンプト文字列への正規表現）
  根拠: planner.yaml context_loading.inject_raw_data_rows = false を
        補強するため、プロンプト自体にもPIIが混入していないことを確認する。
  
  検出例: ユーザーが「田中花子（患者ID: 12345）の血圧を...」と
          入力した場合、氏名・IDをブロックし、
          「患者の血圧を...」への書き直しを促す。


[適用タイミング2]  ─────────────────────────────────────────────
  Contextコンストラクション前
  （全AgentのLLMプロンプト構築直前）
  
  対象: context_payloadに含まれるフィールド名・値
  適用層: Layer 1
  根拠: agent.schema.json ContextLoading.inject_raw_data_rows = const: false
        を実行時に強制的に検証する。
  
  実装: Orchestratorのtask_dispatch_loop Step 4
        「assemble_isolated_context_payload」の直前に実行。


[適用タイミング3]  ─────────────────────────────────────────────
  Data Quality Agent によるdataset_structural_metadata処理時
  
  対象: df.columns（全列名）, SummaryStats.top_categories[].label
  適用層: Layer 1 + Layer 2 + Layer 3（有効時）
  根拠: dataset.schema.json ColumnMetadata.var_n への変換前に実行し、
        PIIを含む可能性のある列名がvar_n_alias_mapに格納される前にブロックする。
  
  このタイミングが最も包括的なフィルタリングポイントである。
  全3層を適用し、検出結果をdata_quality_reportに含める。


[適用タイミング4]  ─────────────────────────────────────────────
  最終レポート出力前（report.schema.json生成前）
  
  対象: manuscript_sections[].content（原稿テキスト）
  適用層: Layer 1 + Layer 3（有効時）
  根拠: Reporting Agentが生成した原稿テキストに、
        var_n復元後のオリジナル列名が意図せず混入していないことを確認する。
  
  Security AgentのSC-007（全token lifecycle記録）と連動し、
  r_code.restore_variablesが適切な経路でのみ呼ばれたことを検証する。
```

---

## 7. 検出後の処理フロー

```
PiiFindings 収集完了
      │
      ├─ CRITICAL findings > 0
      │       │
      │       ▼
      │   IMMEDIATE_ABORT または pipeline_continuation: false
      │   Security Agent通知（security.yaml: SEC-003に準拠）
      │   audit_log に CRITICAL_SECURITY_VIOLATION として記録
      │   Orchestrator → human_approval キューへ追加
      │   UIへの通知: SCR-04 QualityIssueCard（赤）で表示
      │   workflow.state → waiting_for_human
      │
      └─ WARNING findings のみ
              │
              ▼
          自動マスキング処理を提案:
          1. 該当列のvar_nエイリアスを確定（既に処理済みの場合はスキップ）
          2. var_n_alias_map への格納を推奨（Security Agent管理下へ移譲）
          3. top_categories.label のマスキング:
             元の値を "[MASKED-{hash_4chars}]" に置換
          4. audit_log に WARNING として記録
          5. data_quality_report.advisory_findings に追加
          UIへの通知: SCR-04 QualityIssueCard（オレンジ）で表示
```

### 7.1 CRITICAL検出時の人間承認フロー

`security.yaml` の `on_breach_event_detected` と連動する。

```yaml
# security.yamlの該当ハンドラ（参照）
on_pii_critical_detected:
  action: "return_structured_error"
  error_code: "PII_CRITICAL_DETECTED"
  pipeline_continuation: false
  human_escalation: true
  message: >
    PIIの可能性がある情報が検出されました。
    データを確認し、該当列の取り扱いを決定してください。
```

人間が選択できるアクション:
1. **列を除外:** 該当列をanalysis_planから除外してワークフローを再開
2. **エイリアス化を承認:** var_n_alias_mapへの格納を確認してワークフローを再開
3. **誤検出として承認:** 根拠を記入した上でCriticalをWarningに降格してワークフローを再開

---

## 8. var_nエイリアス設計との整合

PII検出フィルタはdataset.schema.jsonの`var_n_alias_map`設計と
以下の形で統合される。

```
[オリジナル列名]
      │
  Layer 1/2/3 検出
      │
      ├─ CRITICAL → ブロック → 人間承認
      │
      └─ WARNING または OK
              │
              ▼
      var_n エイリアスへの変換
      （python_utilities.md extract_structural_metadata()）
              │
              ▼
      var_n_alias_map = { "var_1": "患者ID", "var_2": "氏名", ... }
      ↑ Security Agentの管理下に格納
      ↑ r_code.restore_variables 権限でのみ復元可能
      ↑ permissions.yaml: security agentのみ allow
              │
              ▼
      以降のパイプラインでは var_n のみ流通
      LLMコンテキストに患者情報は混入しない
```

この設計により、PII検出フィルタが見落とした情報であっても、
**var_nエイリアス化がセカンドラインの保護として機能する**。

---

## 9. capability_tokenとの連動

`security.yaml` の capability_token ライフサイクルは
PII検出の強制実行を構造的に保証する。

```
Orchestrator が Data Quality Agentへのタスクを発行
      │
      ▼
Security Agent が ephemeral capability_token を発行
（権限スコープ: dataset.proxy_metadata のみ）
      │
      ▼
Data Quality Agent がPII検出フィルタを実行
（proxy_metadataのみアクセス可: rawデータへのアクセスは権限違反）
      │
      ▼
token 失効（ノード完了後に即時revoke）
      │
  CRITICAL検出時 → token発行前にAbort
  detect後 → audit_log.capture_tool_call_io: true に記録
```

capability_tokenのスコープが`dataset.proxy_metadata`に限定されることで、
PII検出フィルタが**rawデータにアクセスせずに動作する**ことが
アーキテクチャレベルで保証される。

---

## 10. 他コンポーネントとの参照関係

| 参照先 | 参照理由 |
|--------|---------|
| `agents/security.yaml` SC-001 (deny-first) | PII検出の基本方針の源泉 |
| `agents/security.yaml` SEC-002 (PII access review) | CRITICAL検出時の承認フロー |
| `agents/data-quality.yaml` DQ-001 (no raw data) | Layer 2がproxy_metadataのみ使用することの根拠 |
| `agents/planner.yaml` PL-001 (no raw prompt injection) | タイミング1の適用根拠 |
| `agents/runtime.yaml` RT-004 (sanitize stdout) | タイミング4後のランタイムログ保護 |
| `schemas/dataset.schema.json` ColumnMetadata | Layer 2の入力フィールド定義 |
| `schemas/dataset.schema.json` var_n_alias_map | 検出後の変換先スキーマ |
| `schemas/agent.schema.json` inject_raw_data_rows=const:false | 設計レベルの保護の根拠 |
| `schemas/analysis-request.schema.json` natural_language_summary | タイミング1の適用対象フィールド |
| `knowledge/Python/python_utilities.md` extract_structural_metadata() | Layer 1/2の実装ホスト |
| `spec/permissions.yaml` r_code.restore_variables | エイリアス復元の権限制約 |
| `evaluation/security.yaml` SEC-002 (PII protection) | 評価次元との整合 |
