# 別チャットで実装を継続するための指示方法

## Context（なぜこれが必要か）
CIE プロジェクトの MVP 核心実装は「仕様と実装のギャップ監査 → 8フェーズ計画 → フェーズ1完了」まで進んだ。継続に必要な情報はすべてリポジトリ内の2文書に恒久保存済み：
- `docs/DEVELOPER_HANDOFF.md`（別セッションが単体で継続できる技術ハンドオフ）
- `IMPLEMENTATION_PLAN.md`（8フェーズ計画＋進捗、フェーズ1が✅）

現状：ブランチ `feat/mvp-core-llm-r-generation`、PR #4、フェーズ1コミット済み（`d81310b`）。よって別チャットには「この2文書を読んでフェーズ2から続けて」と指示すれば足りる。本書はその指示テンプレートを提供する。

## 別チャットに貼り付ける起動プロンプト（そのままコピペ）

```
このリポジトリ（CIE Platform）の実装を継続してください。

まず以下を順に読んでから着手してください:
1. docs/DEVELOPER_HANDOFF.md  ← 別セッション継続用の技術ハンドオフ（アーキ・データフロー・規約・落とし穴・検証レシピ・フェーズ別ガイド）
2. IMPLEMENTATION_PLAN.md      ← 8フェーズ計画と進捗（フェーズ1は完了✅）
3. CLAUDE.md と decisions/ADR-0001〜0003（絶対ルール）

現状: ブランチ feat/mvp-core-llm-r-generation、フェーズ1（statistical_results生成＋整形）まで完了・コミット済み。

次にやること: フェーズ2「Visualization 実生成」に着手してください。
- StatisticsAgent の LLM＋ナレッジRAG＋キャッシュのR生成パターンを踏襲
- 入力は statistical_results（フェーズ1で供給済み）
- 実行可能な ggplot2 R を生成し、実際のPNG図を出力、figure_manifest に実パスを入れる
- ハーネス（scratchpad/harness_r_exec.py が雛形）で実PNG生成まで検証
- 完了後 python3 -m pytest tests/unit/ が「600 passed／既存失敗15件のみ」を維持することを確認
- IMPLEMENTATION_PLAN.md の該当フェーズを ⬜→✅ に更新

捏造防止・ADR絶対ルール（Plannerにworkflow_id出さない/全Skill更新に人間承認/inject_raw_data_rows=False/Capabilityトークンはtry/finally失効）を厳守してください。
```

## 補足（使い分け）
- **同じフェーズを続けるだけ**なら上記を貼るだけでよい。別チャットは2文書を読めば文脈を復元できる。
- **別のフェーズ（3〜8）をやらせたい**場合は、プロンプト最後の「次にやること」をそのフェーズ名に差し替える（各フェーズの手順は IMPLEMENTATION_PLAN.md と DEVELOPER_HANDOFF.md 第6章に記載済み）。
- **ブランチ運用**: 別チャットにも「feat/mvp-core-llm-r-generation で作業を続ける」か「フェーズごとに新ブランチを切る」かを明示するとよい。
- **Claude のメモリ**（~/.claude/.../memory/）はセッション横断で自動参照されるが、正典はリポジトリ内2文書。別マシン/別環境ではメモリが無いこともあるため、上記プロンプトで文書を明示的に読ませるのが確実。

## 検証（この指示が機能するかの確認方法）
新チャットで起動プロンプトを貼り、エージェントが (a) 2文書を読み、(b) フェーズ2の対象ファイル（cie/agents/visualization.py）と踏襲パターンを正しく述べ、(c) ハーネス検証と pytest 回帰基準に言及すれば、ハンドオフは機能している。
