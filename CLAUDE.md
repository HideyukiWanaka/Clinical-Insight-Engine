# CIE Platform — Claude Code Instructions

## 必ず最初に読むファイル
1. MANIFEST.yaml
2. PROJECT_RULES.md
3. decisions/ADR-0001.md 〜 ADR-0005.md（全て）

## 実装時の絶対ルール
- Plannerの出力にworkflow_idを含めない（ADR-0001）
- DAGノードを実行時に追加・削除・変更しない（ADR-0001）
- 全Skill更新にhuman_review_required=True、SkillLifecycleプロセスを経由（ADR-0002）
- User Skill登録は人間承認必須（ADR-0002）
- knowledge/official/ への書き込み禁止（ADR-0003）
- knowledge/institutional/ への書き込みは人間承認必須、物理削除禁止（Soft Deleteのみ）（ADR-0003）
- ドキュメントパーサーはAbstractDocumentParser経由のみ、直接依存しない（ADR-0003）
- PlannerAgentはSystemWorkflowRegistryにアクセスしない（ADR-0003）
- FrozenKnowledgeSetを実行中にreloadしない（ADR-0003）
- inject_raw_data_rows は常にFalse
- Capability Tokenはtry/finallyで必ず失効
- r_executor.py は変更しない。R変数永続化は上位スクリプトラッパー側で可視の.RDataファイルとして扱う（ADR-0005）

## アーキテクチャ（重要な注意）
- cie/ui/（Streamlit）は削除済み（ADR-0005, commit bb532dc）。参照・復元しない
- 現在の構成: FastAPI（cie/api/）+ React/TypeScript/Vite/Monaco（frontend/）
- ルートのREADME.mdはprompts/README.mdの複製で内容が古い（Streamlit時代の計画）。現状の正はMANIFEST.yaml
