"""CIE Platform — Reporting Agent (Phase 3: LLM + knowledge RAG + journal style).

Generates structured manuscript sections from validated statistical results,
using the LLM grounded in the reporting knowledge reference library.

Key rules (agents/reporting.yaml):
  RP-001  No fabrication: every numeric in manuscript must trace to validated
          statistical_results.  Unverifiable values become unresolved_items.
  RP-002  No raw patient records — only aggregated statistical output.
  RP-003  Apply the appropriate reporting checklist (CONSORT/STROBE/TRIPOD/…).
  RP-004  Flag all authorial decisions as unresolved_items for human review.
  RP-005  Schema-conforming JSON output only.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.audit import AuditService
from cie.core.exceptions import AgentError
from cie.core.llm_client import LLMClient, LLMError
from cie.knowledge.reference_library import MarkdownReferenceLibrary
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import CapabilityScope
from cie.security.policy_engine import PolicyEngine
from cie.skills.loader import SkillLoader

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reporting checklist mapping (reporting.yaml supported_reporting_checklists)
# ---------------------------------------------------------------------------

_CHECKLIST_BY_STUDY_DESIGN: dict[str, str] = {
    "randomized_controlled_trial": "CONSORT",
    "observational": "STROBE",
    "cohort": "STROBE",
    "case_control": "STROBE",
    "cross_sectional": "STROBE",
    "prediction_model": "TRIPOD",
    "systematic_review_or_meta_analysis": "PRISMA",
    "diagnostic_accuracy_study": "STARD",
}

# Minimal checklist item templates per standard (RP-003)
_CHECKLIST_ITEMS: dict[str, list[dict]] = {
    "CONSORT": [
        {"item_id": "CONSORT-1a", "section": "Title", "description": "Identify as RCT in title.", "status": "pending"},
        {"item_id": "CONSORT-1b", "section": "Abstract", "description": "Structured summary of trial.", "status": "pending"},
        {"item_id": "CONSORT-2a", "section": "Introduction", "description": "Background and rationale.", "status": "pending"},
        {"item_id": "CONSORT-2b", "section": "Introduction", "description": "Specific objectives.", "status": "pending"},
        {"item_id": "CONSORT-4a", "section": "Methods", "description": "Eligibility criteria.", "status": "human_required"},
        {"item_id": "CONSORT-6a", "section": "Methods", "description": "Outcomes defined.", "status": "pending"},
        {"item_id": "CONSORT-12a", "section": "Methods", "description": "Statistical methods.", "status": "pending"},
        {"item_id": "CONSORT-13a", "section": "Results", "description": "Participant flow.", "status": "pending"},
        {"item_id": "CONSORT-15", "section": "Results", "description": "Baseline characteristics.", "status": "pending"},
        {"item_id": "CONSORT-17a", "section": "Results", "description": "Outcome results with effect size and CI.", "status": "pending"},
    ],
    "STROBE": [
        {"item_id": "STROBE-1", "section": "Title", "description": "Study design in title or abstract.", "status": "pending"},
        {"item_id": "STROBE-3", "section": "Introduction", "description": "State specific objectives.", "status": "pending"},
        {"item_id": "STROBE-4", "section": "Methods", "description": "Key elements of study design.", "status": "pending"},
        {"item_id": "STROBE-6", "section": "Methods", "description": "Study participants eligibility.", "status": "human_required"},
        {"item_id": "STROBE-8", "section": "Methods", "description": "Variables defined.", "status": "human_required"},
        {"item_id": "STROBE-12", "section": "Methods", "description": "Statistical methods.", "status": "pending"},
        {"item_id": "STROBE-14", "section": "Results", "description": "Participants characteristics.", "status": "pending"},
        {"item_id": "STROBE-16", "section": "Results", "description": "Main results with CI.", "status": "pending"},
        {"item_id": "STROBE-18", "section": "Discussion", "description": "Summary of key results.", "status": "pending"},
        {"item_id": "STROBE-19", "section": "Discussion", "description": "Limitations discussion.", "status": "pending"},
    ],
    "TRIPOD": [
        {"item_id": "TRIPOD-1", "section": "Title", "description": "Prediction model study identified.", "status": "pending"},
        {"item_id": "TRIPOD-2", "section": "Abstract", "description": "Structured abstract.", "status": "pending"},
        {"item_id": "TRIPOD-4a", "section": "Methods", "description": "Study design and data source.", "status": "pending"},
        {"item_id": "TRIPOD-6", "section": "Methods", "description": "Outcome definition.", "status": "pending"},
        {"item_id": "TRIPOD-8", "section": "Methods", "description": "Missing data handling.", "status": "pending"},
        {"item_id": "TRIPOD-10a", "section": "Methods", "description": "Predictor handling.", "status": "pending"},
        {"item_id": "TRIPOD-12", "section": "Results", "description": "Participant flow.", "status": "pending"},
        {"item_id": "TRIPOD-15b", "section": "Results", "description": "Model performance with CI.", "status": "pending"},
    ],
    "PRISMA": [
        {"item_id": "PRISMA-1", "section": "Title", "description": "Systematic review/meta-analysis in title.", "status": "pending"},
        {"item_id": "PRISMA-2", "section": "Abstract", "description": "Structured abstract.", "status": "pending"},
        {"item_id": "PRISMA-3", "section": "Introduction", "description": "Background rationale.", "status": "pending"},
        {"item_id": "PRISMA-4", "section": "Introduction", "description": "Objectives.", "status": "pending"},
        {"item_id": "PRISMA-12", "section": "Methods", "description": "Effect measure specification.", "status": "pending"},
        {"item_id": "PRISMA-16a", "section": "Results", "description": "Search results.", "status": "pending"},
        {"item_id": "PRISMA-20b", "section": "Results", "description": "Synthesis results.", "status": "pending"},
    ],
    "STARD": [
        {"item_id": "STARD-1", "section": "Title", "description": "Diagnostic accuracy study identified.", "status": "pending"},
        {"item_id": "STARD-5", "section": "Methods", "description": "Eligibility criteria.", "status": "human_required"},
        {"item_id": "STARD-10", "section": "Methods", "description": "Test methods.", "status": "pending"},
        {"item_id": "STARD-13", "section": "Results", "description": "Participants flow.", "status": "pending"},
    ],
}

# Canonical unresolved items always requiring human authorial decision (RP-004)
_STANDARD_UNRESOLVED_ITEMS: list[str] = [
    "Clinical interpretation of findings (domain expertise required)",
    "Limitation statements (unexpected findings require expert framing)",
    "Conclusion framing and clinical implications",
    "Acknowledgements and funding statement",
]

# ---------------------------------------------------------------------------
# LLM manuscript generation system prompt (knowledge-grounded)
# ---------------------------------------------------------------------------

_RP_MANUSCRIPT_GEN_SYSTEM_PROMPT = """\
You are a biomedical manuscript writer for the CIE Platform. Generate structured
manuscript sections from validated statistical results.

STRICT REQUIREMENTS:
1. Output ONLY a valid JSON object inside one ```json ... ``` fenced block. No prose outside it.
2. Use ONLY the numbers provided in "statistical_results". Never invent, approximate, or
   extrapolate statistics not present in that object.
3. Include [TRACE: statistical_results.<field>] after every numeric value taken from
   statistical_results (e.g. "p = 0.034 [TRACE: statistical_results.p_value]").
4. Mark every authorial decision requiring human domain knowledge with
   [UNRESOLVED_ITEM: <reason>] (e.g. evidence gap, clinical implications, funding).
5. Apply the journal_style rules provided:
   - APA:       p-values without leading zero, lowercase p (p = .034, p < .001)
   - AMA:       uppercase P, no leading zero (P = .034, P < .001)
   - Vancouver: with leading zero, lowercase p (p = 0.034, p < 0.001)
6. Ground section structure in the MANUSCRIPT STRUCTURE GUIDE reference provided.
7. Do not use causal language ("proves", "confirms causation", "demonstrates that X causes Y").
8. Items marked "human_required" in the reporting checklist must appear in unresolved_items_additions.

OUTPUT JSON SCHEMA (all fields required):
{
  "title_draft": "string",
  "abstract": {
    "background": "string — 1-2 sentences on clinical problem",
    "objective": "string — 1 sentence",
    "methods": "string — study design, population, statistical approach",
    "results": "string — primary result with effect size, CI, p-value [TRACE:] tags",
    "conclusions": "string — 1-2 sentences"
  },
  "introduction": {
    "clinical_problem": "string — 2-3 sentences",
    "evidence_gap": "[UNRESOLVED_ITEM: Literature evidence gap requires human knowledge]",
    "objective_statement": "string — 1 sentence"
  },
  "methods": {
    "study_design": "string",
    "statistical_analysis": "string — include [TRACE: statistical_results.method_id] for test name"
  },
  "results": {
    "sample_description": "string — n=X [TRACE: statistical_results.sample_size]",
    "primary_outcome": "string — use template from result_interpretation_guide with [TRACE:] tags"
  },
  "discussion": {
    "principal_findings": "string — summary paragraph derived from results",
    "literature_comparison": "[UNRESOLVED_ITEM: Comparison with existing literature requires human knowledge]",
    "limitations": "string — list known design limitations, flag others as [UNRESOLVED_ITEM]"
  },
  "conclusions": "string — 2-3 sentences, no new information",
  "unresolved_items_additions": ["string"]
}
"""


class ReportingAgent(BaseAgent):
    """Manuscript section assembly and reporting checklist compliance agent.

    Phase 3: LLM-generated manuscript sections grounded in the knowledge reference
    library (RAG). Falls back to template-based drafting when no LLM is configured,
    preserving existing unit-test compatibility.

    Args:
        policy_engine: Enforces capability scope checks.
        schema_registry: Validates input and output payloads.
        audit_service: Records execution outcomes.
        llm_client: LLM for manuscript generation. None → template-only fallback.
        reference_library: Markdown RAG source (manuscript_structure/result_interpretation).
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        schema_registry: SchemaRegistry,
        audit_service: AuditService,
        llm_client: LLMClient | None = None,
        reference_library: MarkdownReferenceLibrary | None = None,
        skill_loader: SkillLoader | None = None,
    ) -> None:
        super().__init__(policy_engine, schema_registry, audit_service)
        self._llm_client = llm_client
        self._reference_library = reference_library
        self._skill_loader = skill_loader

    @property
    def agent_id(self) -> str:
        return "reporting"

    @property
    def input_schema_ref(self) -> str:
        return "cie://schemas/analysis-request.schema.json"

    @property
    def output_schema_ref(self) -> str:
        return "cie://schemas/manuscript-section.schema.json"

    @property
    def required_scopes(self) -> list[CapabilityScope]:
        # spec/permissions.yaml agent_permission_matrix.reporting allows only
        # report.compile_manuscript + audit.write_entry (deny-first). This
        # agent reads statistical_results from the context payload — it never
        # touches the dataset, so no dataset.* scope is requested.
        return [
            CapabilityScope.REPORT_COMPILE_MANUSCRIPT,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ]

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        """Assemble manuscript sections and reporting checklist status.

        Steps:
          1. RP-002: Verify statistical_results present.
          2. RP-003: Infer or apply reporting checklist.
          3. Read target_journal_style.
          4a. (LLM path) Generate manuscript via LLM + knowledge RAG.
          4b. (Template path) Draft Methods and Results with traceability tags.
          5. Build table specifications.
          6. Collect unresolved_items (RP-004).
          7. Return AgentOutput.
        """
        payload = agent_input.payload

        # Step 1 — RP-002: check statistical_results present
        statistical_results = payload.get("statistical_results")
        if not statistical_results:
            raise AgentError(
                "MISSING_STATISTICAL_INPUT: Manuscript generation requires "
                "validated statistical results from the Statistics Agent.",
                agent_id=self.agent_id,
            )

        # Step 2 — RP-003: infer checklist
        intent_obj: dict = payload.get("intent_object") or {}
        study_design: str = intent_obj.get("study_design", "unknown")
        checklist_id: str | None = (
            payload.get("reporting_checklist_id")
            or _CHECKLIST_BY_STUDY_DESIGN.get(study_design)
        )
        checklist_items = list(_CHECKLIST_ITEMS.get(checklist_id or "", []))

        # Step 3 — journal style (target_journal_style or APA default)
        journal_style: str = (
            payload.get("target_journal_style") or "APA"
        ).upper()
        if journal_style not in {"APA", "AMA", "VANCOUVER"}:
            journal_style = "APA"

        # Skill ID override from format selection UI (Phase 5).
        # When the user explicitly selects a user/ skill for reporting, honour it;
        # otherwise fall back to the canonical core skill "reporting/manuscript-section".
        reporting_skill_id: str = (
            payload.get("reporting_skill_id") or "reporting/manuscript-section"
        )

        # Step 4 — manuscript generation
        figure_manifest: list = payload.get("figure_manifest") or []
        llm_sections: dict | None = None
        llm_provenance: dict = {"llm_generated": False, "knowledge_references": []}

        if self._llm_client is not None:
            llm_sections, llm_provenance = await self._generate_manuscript_with_llm(
                statistical_results=statistical_results,
                intent_obj=intent_obj,
                journal_style=journal_style,
                checklist_id=checklist_id,
                figure_manifest=figure_manifest,
                reporting_skill_id=reporting_skill_id,
            )

        # Build manuscript_sections list
        if llm_sections:
            manuscript_sections, extra_unresolved = self._build_sections_from_llm(
                llm_sections, statistical_results, journal_style
            )
        else:
            # Template fallback (preserves unit-test compatibility)
            methods_text = self._draft_methods_section(intent_obj, statistical_results)
            results_text = self._draft_results_section(statistical_results, journal_style)
            manuscript_sections = [
                {
                    "section_id": "methods",
                    "section_title": "Statistical Methods",
                    "content": methods_text,
                    "traceability_tags": ["intent_object.study_design", "selected_methods"],
                    "word_count": len(methods_text.split()),
                },
                {
                    "section_id": "results",
                    "section_title": "Results",
                    "content": results_text,
                    "traceability_tags": ["statistical_results"],
                    "word_count": len(results_text.split()),
                },
            ]
            extra_unresolved = []

        # Step 5 — table specifications
        group_summaries = statistical_results.get("group_summaries") or {}
        n_groups = len(group_summaries) if isinstance(group_summaries, dict) else 2
        table_specifications = [
            {
                "table_id": "table_1",
                "table_title": "Baseline Characteristics",
                "columns": (
                    ["Variable"] +
                    [f"Group {chr(65+i)}" for i in range(max(n_groups, 2))] +
                    ["p-value"]
                ),
                "source": "statistical_results.baseline_characteristics",
                "note": "Values are mean ± SD or n (%) as appropriate.",
            }
        ]

        # Step 6 — unresolved items (RP-004)
        unresolved_items = list(_STANDARD_UNRESOLVED_ITEMS) + extra_unresolved
        # Deduplicate
        seen: set[str] = set()
        deduped: list[str] = []
        for item in unresolved_items:
            key = item.strip()
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        unresolved_items = deduped

        # Estimate word count
        total_words = sum(s.get("word_count", 0) for s in manuscript_sections)

        # Step 7 — assemble output
        now_iso = datetime.now(timezone.utc).isoformat()
        output_payload: dict = {
            "execution_id": agent_input.execution_id,
            "manuscript_sections": manuscript_sections,
            "table_specifications": table_specifications,
            "reporting_checklist_status": {
                "checklist_id": checklist_id,
                "checklist_version": _CHECKLIST_VERSION.get(checklist_id or ""),
                "checklist_inferred": payload.get("reporting_checklist_id") is None,
                "inference_rationale": (
                    f"study_design='{study_design}' maps to {checklist_id}"
                    if checklist_id
                    else "No checklist could be inferred from study design."
                ),
                "items": checklist_items,
                "compliance_pct": 0.0,
            },
            "unresolved_items": unresolved_items,
            "word_count_estimate": total_words,
            "journal_style": journal_style,
            "manuscript_provenance": llm_provenance,
            "created_at": now_iso,
        }

        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status="success",
            output_payload=output_payload,
            output_schema_ref=self.output_schema_ref,
        )

    # ------------------------------------------------------------------
    # LLM manuscript generation (knowledge-grounded)
    # ------------------------------------------------------------------

    async def _generate_manuscript_with_llm(
        self,
        statistical_results: dict,
        intent_obj: dict,
        journal_style: str,
        checklist_id: str | None,
        figure_manifest: list,
        reporting_skill_id: str = "reporting/manuscript-section",
    ) -> tuple[dict | None, dict]:
        """Generate manuscript sections via LLM grounded in reporting knowledge.

        Returns:
            (sections_dict, provenance). sections_dict is None on failure.
        """
        provenance: dict = {
            "llm_generated": False,
            "knowledge_references": [],
            "journal_style": journal_style,
            "checklist_id": checklist_id,
        }

        # RAG retrieval from knowledge/official/reporting/
        references: list = []
        if self._reference_library is not None:
            method_id = statistical_results.get("method_id", "")
            query_terms = [
                "manuscript structure",
                "result interpretation",
                "reporting checklist",
                method_id,
                checklist_id or "",
                journal_style,
            ]
            references = self._reference_library.retrieve(query_terms, top_k=4)
            provenance["knowledge_references"] = [r.title for r in references]

        # Build prompt (optionally grounded with reporting SKILL.md instructions).
        # Uses the skill_id selected via the format selection UI (Phase 5); falls
        # back to "reporting/manuscript-section" when none is chosen.
        skill_block = (
            self._skill_loader.get_skill_prompt_block(reporting_skill_id)
            if self._skill_loader is not None
            else ""
        )
        system_prompt = _RP_MANUSCRIPT_GEN_SYSTEM_PROMPT + skill_block
        user_message = self._build_manuscript_user_message(
            statistical_results=statistical_results,
            intent_obj=intent_obj,
            journal_style=journal_style,
            checklist_id=checklist_id,
            figure_manifest=figure_manifest,
            references=references,
        )

        try:
            raw = await self._llm_client.complete(system_prompt, user_message)
        except LLMError as exc:
            _log.warning("Manuscript LLM generation failed: %s", exc)
            provenance["reason"] = f"llm_error: {exc}"
            return None, provenance

        sections = self._extract_json_object(raw)
        if not sections:
            _log.warning("Manuscript LLM returned unparseable JSON")
            provenance["reason"] = "empty_or_unparsable_llm_response"
            return None, provenance

        provenance["llm_generated"] = True
        return sections, provenance

    @staticmethod
    def _build_manuscript_user_message(
        statistical_results: dict,
        intent_obj: dict,
        journal_style: str,
        checklist_id: str | None,
        figure_manifest: list,
        references: list,
    ) -> str:
        """Assemble the user turn for manuscript generation."""
        reference_block = "\n\n".join(
            f"### Reference: {r.title}\n{r.excerpt()}" for r in references
        ) or "(no matching reference documents found)"

        # Only include safe statistical result keys (RP-002: no raw data)
        safe_stats = {
            k: v for k, v in statistical_results.items()
            if k in {
                "method_id", "test_name", "test_statistic", "df",
                "p_value", "effect_size", "effect_size_measure",
                "ci_lower", "ci_upper", "sample_size", "group_summaries",
            }
        }

        figure_refs = [
            f.get("figure_id") or f.get("filename") or str(f)
            for f in figure_manifest
        ] if figure_manifest else []

        request = {
            "statistical_results": safe_stats,
            "intent_object": {
                "objective": intent_obj.get("objective"),
                "outcome_type": intent_obj.get("outcome_type"),
                "study_design": intent_obj.get("study_design"),
                "paired": intent_obj.get("paired"),
                "outcome_variables": intent_obj.get("outcome_variables", []),
                "predictor_variables": intent_obj.get("predictor_variables", []),
                "natural_language_summary": intent_obj.get("natural_language_summary", ""),
            },
            "journal_style": journal_style,
            "reporting_checklist_id": checklist_id,
            "figures_available": figure_refs,
        }
        return (
            "Generate a complete set of manuscript sections for the study below.\n\n"
            "=== STUDY CONTEXT ===\n"
            f"{json.dumps(request, ensure_ascii=False, indent=2)}\n\n"
            "=== KNOWLEDGE REFERENCE PATTERNS (ground your writing in these) ===\n"
            f"{reference_block}\n"
        )

    @staticmethod
    def _extract_json_object(raw_text: str) -> dict | None:
        """Extract a JSON object from an LLM response.

        Prefers a fenced ```json ... ``` block; falls back to direct parse.
        """
        match = re.search(r"```(?:json)?\s*\n(.*?)```", raw_text, re.DOTALL)
        if match:
            candidate = match.group(1).strip()
        else:
            candidate = raw_text.strip()

        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    # ------------------------------------------------------------------
    # Build manuscript_sections from LLM output
    # ------------------------------------------------------------------

    def _build_sections_from_llm(
        self,
        llm_sections: dict,
        statistical_results: dict,
        journal_style: str,
    ) -> tuple[list[dict], list[str]]:
        """Convert the LLM JSON output into manuscript_sections list + unresolved additions."""
        sections: list[dict] = []
        extra_unresolved: list[str] = list(llm_sections.get("unresolved_items_additions", []))

        def _make_section(section_id: str, title: str, content: Any) -> dict:
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            return {
                "section_id": section_id,
                "section_title": title,
                "content": text,
                "traceability_tags": ["statistical_results"],
                "word_count": len(text.split()),
                "llm_generated": True,
            }

        # Title draft
        if llm_sections.get("title_draft"):
            sections.append(_make_section("title", "Title Draft", llm_sections["title_draft"]))

        # Abstract (structured subsections joined)
        abstract = llm_sections.get("abstract", {})
        if isinstance(abstract, dict) and abstract:
            abstract_text = "\n\n".join(
                f"**{k.capitalize()}:** {v}"
                for k, v in abstract.items() if v
            )
            sections.append(_make_section("abstract", "Abstract", abstract_text))

        # Introduction
        intro = llm_sections.get("introduction", {})
        if isinstance(intro, dict) and intro:
            intro_text = "\n\n".join(v for v in intro.values() if v)
            sections.append(_make_section("introduction", "Introduction", intro_text))

        # Methods — must contain [TRACE:] tags (enforced by prompt; add fallback check)
        methods_data = llm_sections.get("methods", {})
        if isinstance(methods_data, dict) and methods_data:
            methods_text = "\n\n".join(v for v in methods_data.values() if v)
        else:
            methods_text = str(methods_data) if methods_data else ""

        # Ensure [TRACE:] present in methods for RP-001 (fallback append if LLM missed it)
        method_id = statistical_results.get("method_id")
        if method_id and "[TRACE:" not in methods_text:
            methods_text += (
                f" [TRACE: statistical_results.method_id={method_id!r}]"
            )
        if methods_text:
            sections.append({
                "section_id": "methods",
                "section_title": "Methods",
                "content": methods_text,
                "traceability_tags": ["intent_object.study_design", "selected_methods"],
                "word_count": len(methods_text.split()),
                "llm_generated": True,
            })

        # Results — must contain [TRACE:] tags (RP-001)
        results_data = llm_sections.get("results", {})
        if isinstance(results_data, dict) and results_data:
            results_text = "\n\n".join(v for v in results_data.values() if v)
        else:
            results_text = str(results_data) if results_data else ""

        p_value = statistical_results.get("p_value")
        if p_value is not None and "[TRACE:" not in results_text:
            p_str = self._format_p_value(p_value, journal_style)
            results_text += (
                f" {p_str} [TRACE: statistical_results.p_value]"
            )
        if results_text:
            sections.append({
                "section_id": "results",
                "section_title": "Results",
                "content": results_text,
                "traceability_tags": ["statistical_results"],
                "word_count": len(results_text.split()),
                "llm_generated": True,
            })

        # Discussion
        discussion = llm_sections.get("discussion", {})
        if isinstance(discussion, dict) and discussion:
            discussion_text = "\n\n".join(v for v in discussion.values() if v)
            sections.append(_make_section("discussion", "Discussion", discussion_text))

        # Conclusions
        conclusions = llm_sections.get("conclusions")
        if conclusions:
            sections.append(_make_section("conclusions", "Conclusions", conclusions))

        return sections, extra_unresolved

    # ------------------------------------------------------------------
    # Template-based fallback drafting (preserves unit-test compatibility)
    # ------------------------------------------------------------------

    def _draft_methods_section(
        self, intent_obj: dict, statistical_results: dict
    ) -> str:
        """Draft the Statistical Methods section with traceability tags."""
        objective = intent_obj.get("objective", "unspecified")
        study_design = intent_obj.get("study_design", "unspecified")
        method_id = statistical_results.get("method_id", "unspecified")
        return (
            f"Statistical analyses were performed using R (version ≥ 4.3). "
            f"The study design was {study_design}. "
            f"The primary analysis objective was {objective}. "
            f"The primary statistical test was {method_id} "
            f"[TRACE: statistical_results.method_id]. "
            f"Effect sizes and 95% confidence intervals are reported for all primary outcomes. "
            f"A two-sided significance threshold of α = 0.05 was applied."
        )

    def _draft_results_section(
        self, statistical_results: dict, journal_style: str = "APA"
    ) -> str:
        """Draft the Results section. Values traced to statistical_results."""
        p_value = statistical_results.get("p_value")
        effect_size = statistical_results.get("effect_size")
        n_total = statistical_results.get("n_total") or statistical_results.get("sample_size")

        p_str = (
            self._format_p_value(p_value, journal_style)
            if isinstance(p_value, float)
            else "p = [TRACE: p_value]"
        )
        es_str = (
            f"effect size = {effect_size:.2f} [TRACE: statistical_results.effect_size]"
            if isinstance(effect_size, (int, float))
            else "effect size = [TRACE: effect_size]"
        )
        n_str = (
            f"{n_total} [TRACE: statistical_results.n_total]"
            if n_total is not None
            else "[TRACE: n_total]"
        )

        return (
            f"A total of {n_str} participants were included in the primary analysis "
            f"[TRACE: statistical_results.n_total]. "
            f"The primary outcome showed {p_str} ({es_str}), "
            f"with a 95% confidence interval of [TRACE: confidence_interval]. "
            f"Detailed results are presented in Table 1."
        )

    # ------------------------------------------------------------------
    # Journal style p-value formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_p_value(p_value: float, journal_style: str) -> str:
        """Format a p-value according to the target journal style.

        APA 7th:   no leading zero, lowercase p  (p = .034, p < .001)
        AMA:       no leading zero, uppercase P  (P = .034, P < .001)
        Vancouver: with leading zero, lowercase p (p = 0.034, p < 0.001)
        """
        style = journal_style.upper()
        if style == "APA":
            if p_value < 0.001:
                return "p < .001"
            return f"p = {p_value:.3f}".replace("0.", ".")
        if style == "AMA":
            if p_value < 0.001:
                return "P < .001"
            return f"P = {p_value:.3f}".replace("0.", ".")
        # Vancouver (default)
        if p_value < 0.001:
            return "p < 0.001"
        return f"p = {p_value:.3f}"


# Checklist version map for output metadata
_CHECKLIST_VERSION: dict[str, str] = {
    "CONSORT": "2010",
    "STROBE": "2007",
    "TRIPOD": "2024",  # TRIPOD+AI supersedes TRIPOD 2015
    "PRISMA": "2020",
    "STARD": "2015",
}
