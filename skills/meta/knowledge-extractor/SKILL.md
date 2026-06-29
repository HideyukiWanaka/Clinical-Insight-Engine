# SKILL: Knowledge Extractor
# Skill ID: meta/knowledge-extractor
# Version: 1.0.0
# Namespace: meta
# Consumers: knowledge-ingestion agent (KIP Phase 2 — ADR-0003)
# Knowledge references:
#   - decisions/ADR-0003.md (Knowledge Ingestion Pipeline)
#   - spec/system-workflow.yaml (kip_knowledge_ingestion workflow)
#   - schemas/knowledge-entry.schema.json

## Overview

Extracts structured knowledge entries from parsed document content produced
by the Knowledge Ingestion Pipeline (KIP).

The Knowledge Extractor takes `DocumentChunk` objects (plain text, tables,
figures) from the AbstractDocumentParser output and produces validated
`KnowledgeEntry` objects conforming to `schemas/knowledge-entry.schema.json`.

This Skill does NOT write to `knowledge/official/` or `knowledge/institutional/`.
It produces candidate entries only. Human Authority approves before persistence.

---

## Triggers

Invoked by the `knowledge-ingestion` agent during KIP Phase 2:
- `kip_knowledge_ingestion` system workflow node `extract_knowledge`

---

## Inputs

| Field | Type | Description |
|-------|------|-------------|
| chunks | list[DocumentChunk] | Parsed document segments |
| source_doc_id | str | Unique identifier of the source document |
| extraction_context | dict | Domain hints provided by the submitter |

---

## Outputs

`list[KnowledgeEntryDraft]` conforming to `schemas/knowledge-entry.schema.json`
with `status: pending_human_review`.

---

## Procedure

### Step 1 — Chunk Classification

Classify each `DocumentChunk` by knowledge domain:
- `statistics` — methodology, assumptions, test conditions
- `clinical` — clinical interpretation norms
- `reporting` — table/figure conventions
- `R` or `Python` — code patterns and library usage

### Step 2 — Structured Extraction

For each relevant chunk, extract:
- `title`: concise name for the knowledge entry
- `content`: structured Markdown with key statements
- `source_reference`: document ID + page/section reference
- `domain`: one of the domains above

### Step 3 — Schema Validation

Validate each draft against `schemas/knowledge-entry.schema.json`.
Invalid entries are logged to AuditLog with `event_severity: WARNING` and skipped.

### Step 4 — Output

Return validated `KnowledgeEntryDraft` objects to the `knowledge-ingestion` agent
for persistence to `knowledge/pending/`.

---

## Invariants

- Never writes directly to `knowledge/official/` or `knowledge/institutional/`
- All output entries have `status: pending_human_review`
- `human_review_required` is always `True` on every produced entry
