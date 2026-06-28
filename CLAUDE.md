# CIE Platform — Claude Code Instructions

## 必ず最初に読むファイル
1. MANIFEST.yaml
2. PROJECT_RULES.md
3. decisions/ADR-0001.md
4. decisions/ADR-0002.md

## 実装時の絶対ルール
- Plannerの出力にworkflow_idを含めない（ADR-0001）
- 全Skill更新にhuman_review_required=True（ADR-0002）
- inject_raw_data_rows は常にFalse
- Capability Tokenはtry/finallyで必ず失効