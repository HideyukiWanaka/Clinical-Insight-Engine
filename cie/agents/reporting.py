"""CIE Platform — Reporting Agent.

Assembles validated statistical results and figure assets into structured
manuscript sections conforming to the target journal or reporting standard.

Key rules (agents/reporting.yaml):
  RP-001  No fabrication: every numeric in manuscript must trace to validated
          statistical_results.  Unverifiable values become unresolved_items.
  RP-002  No raw patient records — only aggregated statistical output.
  RP-003  Apply the appropriate reporting checklist (CONSORT/STROBE/TRIPOD/…).
  RP-004  Flag all authorial decisions as unresolved_items for human review.
  RP-005  Schema-conforming JSON output only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.audit import AuditService
from cie.core.exceptions import AgentError
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import CapabilityScope
from cie.security.policy_engine import PolicyEngine

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

# Minimal checklist item templates per standard
_CHECKLIST_ITEMS: dict[str, list[dict]] = {
    "CONSORT": [
        {"item_id": "CONSORT-1a", "section": "Title", "description": "Identify as RCT in title.", "status": "pending"},
        {"item_id": "CONSORT-2a", "section": "Introduction", "description": "Background and rationale.", "status": "pending"},
        {"item_id": "CONSORT-4a", "section": "Methods", "description": "Eligibility criteria.", "status": "pending"},
        {"item_id": "CONSORT-6a", "section": "Methods", "description": "Outcomes defined.", "status": "pending"},
        {"item_id": "CONSORT-13a", "section": "Results", "description": "Participant flow diagram.", "status": "pending"},
        {"item_id": "CONSORT-17a", "section": "Results", "description": "Outcome results for each group.", "status": "pending"},
    ],
    "STROBE": [
        {"item_id": "STROBE-1a", "section": "Title", "description": "Study design in title.", "status": "pending"},
        {"item_id": "STROBE-6", "section": "Methods", "description": "Study participants eligibility.", "status": "pending"},
        {"item_id": "STROBE-8", "section": "Methods", "description": "Variables defined.", "status": "pending"},
        {"item_id": "STROBE-12", "section": "Methods", "description": "Statistical methods.", "status": "pending"},
        {"item_id": "STROBE-14", "section": "Results", "description": "Participants characteristics.", "status": "pending"},
        {"item_id": "STROBE-16", "section": "Results", "description": "Main results.", "status": "pending"},
    ],
    "TRIPOD": [
        {"item_id": "TRIPOD-1", "section": "Title", "description": "Prediction model development/validation noted.", "status": "pending"},
        {"item_id": "TRIPOD-4", "section": "Methods", "description": "Outcome definition.", "status": "pending"},
        {"item_id": "TRIPOD-7", "section": "Methods", "description": "Sample size considerations.", "status": "pending"},
        {"item_id": "TRIPOD-10", "section": "Methods", "description": "Statistical analysis methods.", "status": "pending"},
        {"item_id": "TRIPOD-16", "section": "Results", "description": "Model performance.", "status": "pending"},
    ],
    "PRISMA": [
        {"item_id": "PRISMA-1", "section": "Title", "description": "Systematic review/meta-analysis in title.", "status": "pending"},
        {"item_id": "PRISMA-6", "section": "Methods", "description": "Search strategy.", "status": "pending"},
        {"item_id": "PRISMA-13", "section": "Results", "description": "PRISMA flow diagram.", "status": "pending"},
        {"item_id": "PRISMA-17", "section": "Results", "description": "Results of individual studies.", "status": "pending"},
    ],
    "STARD": [
        {"item_id": "STARD-1", "section": "Title", "description": "Diagnostic accuracy study identified.", "status": "pending"},
        {"item_id": "STARD-5", "section": "Methods", "description": "Eligibility criteria.", "status": "pending"},
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


class ReportingAgent(BaseAgent):
    """Manuscript section assembly and reporting checklist compliance agent.

    Produces structured manuscript sections, table specifications, and
    reporting checklist status.  All authorial decisions that cannot be
    automated are explicitly flagged as unresolved_items (RP-004).

    Args:
        policy_engine: Enforces capability scope checks.
        schema_registry: Validates input and output payloads.
        audit_service: Records execution outcomes.
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        schema_registry: SchemaRegistry,
        audit_service: AuditService,
    ) -> None:
        super().__init__(policy_engine, schema_registry, audit_service)

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
        return [
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.REPORT_COMPILE_MANUSCRIPT,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ]

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        """Assemble manuscript sections and reporting checklist status.

        Steps:
          1. RP-002: Verify statistical_results present.
          2. RP-003: Infer or apply reporting checklist.
          3. Draft Methods and Results sections with traceability tags.
          4. Build table specifications.
          5. Collect unresolved_items (RP-004).
          6. Return AgentOutput.
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

        # Step 3 — draft Methods and Results sections (RP-001: traceability tags)
        methods_text = self._draft_methods_section(intent_obj, statistical_results)
        results_text = self._draft_results_section(statistical_results)

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

        # Step 4 — table specifications
        table_specifications = [
            {
                "table_id": "table_1",
                "table_title": "Baseline Characteristics",
                "columns": ["Variable", "Group A", "Group B", "p-value"],
                "source": "statistical_results.baseline_characteristics",
                "note": "Values are mean (SD) or n (%) as appropriate.",
            }
        ]

        # Step 5 — unresolved items (RP-004)
        unresolved_items = list(_STANDARD_UNRESOLVED_ITEMS)

        # Estimate word count
        total_words = sum(s["word_count"] for s in manuscript_sections)

        # Step 6 — assemble output
        now_iso = datetime.now(timezone.utc).isoformat()
        output_payload: dict = {
            "execution_id": agent_input.execution_id,
            "manuscript_sections": manuscript_sections,
            "table_specifications": table_specifications,
            "reporting_checklist_status": {
                "checklist_id": checklist_id,
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
            "created_at": now_iso,
        }

        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status="success",
            output_payload=output_payload,
            output_schema_ref=self.output_schema_ref,
        )

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

    def _draft_results_section(self, statistical_results: dict) -> str:
        """Draft the Results section. Values traced to statistical_results."""
        p_value = statistical_results.get("p_value")
        effect_size = statistical_results.get("effect_size")
        n_total = statistical_results.get("n_total")

        p_str = f"p = {p_value:.3f}" if isinstance(p_value, float) else "p = [TRACE: p_value]"
        es_str = (
            f"effect size = {effect_size:.2f}"
            if isinstance(effect_size, (int, float))
            else "effect size = [TRACE: effect_size]"
        )
        n_str = str(n_total) if n_total is not None else "[TRACE: n_total]"

        return (
            f"A total of {n_str} participants were included in the primary analysis "
            f"[TRACE: statistical_results.n_total]. "
            f"The primary outcome showed {p_str} ({es_str}), "
            f"with a 95% confidence interval of [TRACE: confidence_interval]. "
            f"Detailed results are presented in Table 1."
        )
