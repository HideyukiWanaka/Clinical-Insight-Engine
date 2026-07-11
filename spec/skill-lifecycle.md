# Skill Lifecycle Specification

**Version:** 1.0.0
**Status:** Active
**ADR Reference:** ADR-0002 — Meta-Skills and Self-Improving Skill Architecture

---

## Overview

This document defines the lifecycle process for creating, updating, and retiring
CIE Platform Skills. All Skill mutations require human approval (ADR-0002 Principle 4).

---

## Lifecycle Phases

### Phase 1: Detection

Automated triggers that initiate the Skill Lifecycle:

| Trigger ID | Condition |
|-----------|-----------|
| SE-001 | Recurring advisory finding ≥ 3 of last 5 executions |
| SE-002 | Skill pass rate < 80% over last 10 executions |
| SE-003 | Test failure on new data pattern |
| SE-004 | Manual request from Human Authority |

Trigger detection is performed by `meta/skill-evaluator/`.

### Phase 2: Proposal Generation

When a trigger fires, `meta/skill-proposer/` generates a `SkillImprovementProposal`:

- Reads the current Skill version from the namespace
- Produces proposed changes as a structured diff
- Sets `human_review_required = True` (invariant — cannot be overridden)
- Persists the proposal as a `SkillImprovementProposalRow` in the database

### Phase 3: Human Review

**Human Authority** reviews the proposal:

- `approved` → proceeds to Phase 4
- `rejected` → archived, no change to Skill
- No auto-approval path exists (ADR-0002 Principle 4)

### Phase 4: Version Archive

Before any Skill file is modified:

1. Current version is archived to `versions/<current_version>/`
2. Archive includes all files in the skill directory (SKILL.md, examples/, tests/)
3. Archive is immutable after creation

### Phase 5: Deployment

`skill_lifecycle` agent applies the approved change:

- For `core/` Skills: requires `skill.update_core` scope
- For `user/` Skills: requires `skill.register_user` scope
- Scope issuance records the human approval reference

---

## Namespace Rules

| Namespace | Update Authority | Overridable |
|-----------|-----------------|-------------|
| `core/` | CIE Team + Human Authority | No |
| `meta/` | CIE Team only + Human Authority | No |
| `user/` | Facility Admin + Human Authority | Overrides core/ with same skill_id |

---

## Invariants

- `inject_raw_data_rows = const: false` — Skills never receive raw patient data
- `human_review_required = True` — All proposals require human approval
- Core Skill `versions/` directories are append-only — no deletion permitted
- `skill_lifecycle` agent is the sole agent with `skill.update_core` scope

---

## Authoring a new statistics Skill

For a concrete, copy-pasteable template of a statistics SKILL.md — its required
`# Version:` header, section structure (Overview / Applies when / Procedure /
Validation Rules), the directory layout `SkillLoader.discover()` expects, and
the `cie/agents/statistics.py` wiring (`_METHODS` / `_METHOD_TO_SKILL_ID` /
`_select_method`) that clears the off-catalogue (`off_catalog`) warning — see
[docs/authoring-a-statistics-skill.md](../docs/authoring-a-statistics-skill.md).
