# 生成AI実装における仕様ギャップ防止ナレッジ

このドキュメントは CIE プロジェクトで判明した、生成AI（主にLLM）を使った実装時に「仕様があるのに実装されていない」という落とし穴を防ぐためのナレッジです。

## 背景：今回なぜギャップが生じたのか

2026年7月初旬の実装で、初期フェーズ（1-10）として「Visualization/Reporting/Skill自己改善」等の仕様が書かれていた。しかし実装を調査すると：

| 機能 | 仕様ファイル | 実装コード | 状態 |
|------|-----------|---------|------|
| Visualization | agents/visualization.yaml ✓ | ggplot2「仕様」のみ、LLM呼び出しなし | スケルトン |
| Reporting | reporting.yaml ✓ | テンプレート断片、LLM未使用 | スケルトン |
| Skill適用 | ADR-0002, MANIFEST ✓ | SkillLoader呼出しゼロ | スケルトン |
| 評価ステージ | evaluation/, workflow.yaml ✓ | モジュールはあるがワークフロー未接続 | 未統合 |
| decisionルーティング | workflow.yaml rules定義 ✓ | Orchestrator に rules評価コードなし | 実装漏れ |

つまり「仕様ファイルの存在 ≠ 実装完了」が、実装チェックなしで次のPhaseに進んでしまった。

## 生成AI実装時に「スケルトン化」が起きやすい理由

### 1. 指示の曖昧さ
**ダメな例**
```
Visualization エージェントを実装してください。
spec/agents/visualization.yaml を参考にしてください。
```
LLMは「仕様を読んで、その構造に従う出力を返す」という**パッシブな実装**に終わりやすい。生成API呼び出しが入るべき箇所で「仕様ファイルの値をコピーしただけ」状態。

### 2. 統合テスト不在
**ダメな例**
```python
# tests/unit/test_visualization.py
def test_visualization_output_schema():
  vo = VisualizationAgent(...)
  out = vo._execute(agent_input)
  assert out.output_payload["visualization_specifications"] is not None  # ✓パス
  # → 実は visualization_specifications は「仕様」であって、実行可能Rではない
```
単体テストは「型が合うか」を見るだけで、「実際に図が生成されるか」を見ていない。

### 3. 実装者の文脈不足
LLMは（セッション継続時に）前のPhaseが「仕様のみか、実装済みか」を区別しない。「visualization.yamlがあるなら、ここは完成してるんだろう」と過程する→下流で「なぜ statistical_results が来ないのか」という予期しない入力で失敗する。

## 防止策6点（具体的・実践的）

### 1️⃣ 指示テンプレート：「仕様の**どこまで**を実装するか」を明示

**良い指示例**
```
Visualization Agent（Phase 2）を実装します。

【仕様】spec/agents/visualization.yaml
【既存】Phase 1 で statistical_results（下流契約キー）が供給済み

【実装範囲】
- ✅ LLMClient + reference_library を注入してR生成（statistics.py のパターンを踏襲）
- ✅ 入力：statistical_results（フェーズ1で供給済み）
- ✅ 出力：executable ggplot2 R、実PNG図、figure_manifest に実パス
- ✅ ハーネス（harness_visualization_exec.py）で実PNG生成を確認
- ❌ 日本語ラベル自動生成（Phase 5 以降）
- ❌ インタラクティブプロット（Phase 以降）

【踏襲パターン】
- statistics.py の _R_GEN_SYSTEM_PROMPT 構造
- reference_library.retrieve() でナレッジRAG
- RScriptCache でキャッシュ

【検証（必須）】
- ハーネスで実R実行→PNG生成を確認
- pytest が 600 passed（既存失敗15件のみ）を維持
- IMPLEMENTATION_PLAN.md でこのPhaseを ⬜→✅ に更新
```

この指示なら、LLMが「仕様だけ実装」する可能性が大幅に低下。

### 2️⃣ ハーネステンプレを Phase 計画時に提供

**パターン**
```python
# scratchpad/harness_visualization_exec.py — Phase 2 用ハーネス雛形

import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, "/Users/.../Clinical insight engine")

from cie.agents.statistics import StatisticsAgent
from cie.agents.visualization import VisualizationAgent
from cie.agents.runtime import RuntimeAgent
# ... (stubs, test data)

# Step 1: Statistics（LLMスタブで実行）→ statistical_results を得る
# Step 2: Visualization（実装対象）→ r_script を生成
# Step 3: Runtime（実R実行）→ PNG を生成
# Step 4: 検証：output_dir/figure_*.png が存在すること

if __name__ == "__main__":
  # ... 実装
  print("✓ PNG 生成成功、パス:", figure_path)
```

このテンプレを「Phase計画の時点で」提供し、「このハーネスが動くまで実装は完了ではない」を明確にする。

### 3️⃣ 統合テスト（integration tests）を必須に

**例**
```python
# tests/integration/test_phase2_visualization_e2e.py
def test_visualization_generates_real_png():
  """Phase 1 (statistics) → Phase 2 (visualization) の E2E.
  
  実CSV・実LLMスタブで、statistical_results から実PNG が生成されること。
  """
  # 1. intent → statistics (LLMスタブ) → statistical_results
  sr = {"test_name": "t-test", "p_value": 0.01, ...}
  
  # 2. statistical_results → visualization (実装対象) → r_script
  viz_out = visualization_agent._execute(agent_input)
  assert "r_script" in viz_out.output_payload
  assert "```r" in viz_out.output_payload["r_script"]
  
  # 3. r_script → runtime (実R) → PNG
  png_path = runtime_agent._execute(...)
  assert png_path.exists()
  assert png_path.suffix == ".png"
```

単体テストと違い、「実装したコードが実際に期待の成果物（PNG、JSON、テキスト等）を生むか」を確認。

### 4️⃣ 「仕様→実装マッピング表」を実装時に作成・検証

Phase計画の段階で
```markdown
## Phase 3: Reporting 実装

### 仕様→実装マッピング
| 仕様項目 | spec/agents/reporting.yaml 行 | 実装ファイル | 実装行 | 状態 |
|---------|--------------------------|---------|------|------|
| target_journal_style 読取 | L55 | cie/agents/reporting.py | 156 | ✅ |
| reporting_checklist_id 推論 | L89-90 | reporting.py | 180-200 | ✅ |
| LLM統合（原稿生成） | L4-7 | reporting.py | 240-280 | ✅ |
| ナレッジRAG | L8 | reporting.py | 290-310 | ✅ |
| manuscript_sections 出力 | L60 | reporting.py | 350 | ✅ |
```

これを Phase 末に「全項目✅」にすることを完了基準とする。

### 5️⃣ 「ギャップ監査」を Phase 開始時に実施（本セッション でやったもの）

新しいPhaseを始める前に、**前のPhaseが仕様を満たしているか**を確認：

```bash
# Phase 2 開始前に、Phase 1（Statistics）が仕様満たしているか確認
echo "=== 仕様にある機能 ==="
grep -E "output|generate|LLM" agents/statistics.yaml | wc -l  # 5項目

echo "=== 実装されている機能 ==="
grep -E "llm_client|reference_library|_generate_r_script" cie/agents/statistics.py | wc -l

# 数が合わない → ギャップあり → 修正してから次Phase
```

### 6️⃣ ハンドオフ＆チェックリスト（各Phase末）

**本セッション の DEVELOPER_HANDOFF.md / CONTINUATION_PROMPT.md の原型**

```markdown
# Phase 2 完了チェックリスト

## 実装
- [ ] VisualizationAgent に llm_client, reference_library, script_cache を注入
- [ ] _generate_ggplot2_script() メソッド実装（statistics パターン踏襲）
- [ ] 実行可能 ggplot2 R を生成（```r ... ``` で抽出）
- [ ] Runtime で実PNG を生成、figure_manifest に実パス
- [ ] ハーネス harness_visualization_exec.py で実PNG生成を実証

## テスト
- [ ] ユニットテスト（tests/unit/test_visualization.py）が新規失敗なし
- [ ] 統合テスト（tests/integration/test_phase2_visualization_e2e.py）が実PNG確認
- [ ] pytest 全体が 600 passed（既存失敗15件のみ）を維持

## ドキュメント
- [ ] IMPLEMENTATION_PLAN.md のPhase 2 を ⬜→✅ に更新
- [ ] ハーネスの実行手順を記す

## 次Phase への引き継ぎ
- [ ] 本checklist をPR コミットメッセージに記す
- [ ] Phase 3 実装者へ「Phase 2 のハーネス（harness_visualization_exec.py）を参考に、Phase 3 用ハーネスを作成」と指示
```

---

## 生成AI実装特有の注意点3つ

### A. LLM が「仕様ファイルをコピーしたかのような出力」を返す罠

```python
# ❌ ダメ例：仕様ファイルの値をそのまま辞書にした
_METHODS = {
  "t_test": {"name": "t-test", "assumptions": [...]}  # spec/agents/ から丸コピー
}
# → 実行可能Rコードがない、LLM呼び出しもない

# ✅ 良い例：LLM呼び出しまで指示に含める
# 指示："_generate_r_script() を実装してください。stats.yaml を参考にしながら、
# LLMClient で stat+intent → ナレッジRAG → R生成 のフローを実装"
```

LLMに「参考にしてください」と言うと、参照元をコピーしがち。**「このコード片はスタブです。ここにLLM呼び出しを追加してください」**と明示が効果的。

### B. 「optional 入力」が実装されない

```yaml
# spec/agents/reporting.yaml
optional:
  - "target_journal_style"  # e.g., APA, AMA, Vancouver
```

LLMは「optional」を見ると「あってもなくても動く」と解釈し、読み込むコード自体を書かないことがある。

**防止策**：指示に「以下の3つのフォーマットで出力を変える実装が必須」と明記。

### C. ワークフロー統合（キー受け渡し）の見落とし

```python
# ❌ 実装者が見落としやすい
# visualization が出力する figure_manifest を、
# reporting が読み込む契約（reporting.py: payload.get("figure_manifest")）
# が、実際にOrchestrator の accumulated_context マージでつながっているか
# 確認されていない。

# ✅ 防止策
# ハーネスで明示的に：
#   statistic_out → visualization_in（figure_manifest 期待）
#   visualization_out → reporting_in（figure_manifest 実際に送られたか確認）
```

---

## チェックリスト：新しい Phase を始める前に

```
[ ] 前のPhase の仕様ギャップ監査を実施。全項目✅か確認
[ ] Phase 計画で「仕様のどこまでを実装するか」を明示
[ ] ハーネステンプレを Phase 計画の段階で作成
[ ] 指示テンプレに「踏襲パターン」を記す（reference_library/RScriptCache等）
[ ] 実装完了後、仕様→実装マッピング表を埋める
[ ] 統合テスト（ハーネス + pytest）で実成果物（PNG/JSON/テキスト）を生成確認
[ ] IMPLEMENTATION_PLAN.md を ⬜→✅ に更新
[ ] ハンドオフ＆チェックリストを作成し、次Phase への引き継ぎを記す
```

---

## 本プロジェクトで実装した対策

フェーズ1（本セッション）で以下を実装・記録：

| 対策 | ファイル | 効果 |
|------|---------|------|
| ハーネステンプレ | scratchpad/harness_r_exec.py | Phase 2+ が同じ形式で検証可能に |
| Phase計画＋チェックリスト | IMPLEMENTATION_PLAN.md | 次Phase が「何を実装すべきか」が明確 |
| 仕様→実装マッピング | DEVELOPER_HANDOFF.md第7章 | Phase の完了度が可視化 |
| ギャップ監査テンプレ | 本書（AI_IMPLEMENTATION_LESSONS.md） | Phase開始時の監査が標準化 |
| ハンドオフドキュメント | CONTINUATION_PROMPT.md | 次セッションが冷えた状態から文脈復元可能 |

---

## 今後のプロジェクト運営方針

1. **各Phase末に、このドキュメント冒頭の「仕様ギャップ監査」を実施**
   - 新しいPhaseを始める前に「前のPhaseが本当に完成か」を網羅的に確認
   
2. **ハーネスを「成果物」の一部として扱う**
   - コードだけでなく「実データで動くハーネス」を交付しないとPhase完了と見なさない
   
3. **統合テストを CI に組み込む**
   - PR マージ前に「このPhaseで期待の成果物（図・文章等）が生まれるか」を確認
   
4. **指示テンプレを毎Phaseで改善**
   - 「これまでのギャップ実例」を踏まえ、次の指示をより具体的に

---

## まとめ

生成AI実装で「仕様だけあって実装がない」落とし穴を防ぐには：

> **①指示を明確に＋踏襲パターン明示　②ハーネス（実データE2E）必須　③統合テスト＋ギャップ監査　④ハンドオフドキュメント　⑤Phase末チェックリスト**

本セッションで判明したギャップ10項目は、この5つを適用することで大部分は初期段階で検出・防止できます。
