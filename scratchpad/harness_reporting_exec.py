"""Phase 3 harness: ReportingAgent LLM+RAG+journal style manuscript generation.

Usage:
    python3 scratchpad/harness_reporting_exec.py

Verifies:
- APA + STROBE path: LLM-generated manuscript sections with [TRACE:] tags
- journal_style=APA: p-values formatted as "p = .034" / "p < .001"
- Checklist inferred from study_design='cohort' → STROBE
- unresolved_items populated (RP-004)
- figure_manifest consumed from payload
- Template fallback (llm_client=None) still produces [TRACE:] tags
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Ensure repo root is on path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from cie.agents.base import AgentInput
from cie.agents.reporting import ReportingAgent
from cie.knowledge.reference_library import MarkdownReferenceLibrary
from cie.security.capability_token import CapabilityScope, CapabilityToken

# ---------------------------------------------------------------------------
# Stub LLM — returns a well-formed JSON manuscript
# ---------------------------------------------------------------------------

_MOCK_MANUSCRIPT_JSON = {
    "title_draft": "Comparative Effectiveness in a Cohort Study: Outcomes at 12 Months",
    "abstract": {
        "background": "Comparison of treatment outcomes between groups is a critical step in cohort research.",
        "objective": "To determine whether Group A demonstrates superior outcomes compared with Group B.",
        "methods": "A retrospective cohort study. Primary analysis used an independent samples t-test. Effect size reported as Cohen's d with 95% CI.",
        "results": (
            "Among 80 participants, the primary outcome differed significantly between groups "
            "(p = .034 [TRACE: statistical_results.p_value]; "
            "Cohen's d = 0.52 [TRACE: statistical_results.effect_size]; "
            "95% CI: 0.12 to 0.92 [TRACE: statistical_results.ci_lower / ci_upper])."
        ),
        "conclusions": "The primary outcome favoured Group A. [UNRESOLVED_ITEM: Clinical implications require expert review]",
    },
    "introduction": {
        "clinical_problem": "Between-group differences in clinical outcomes are of sustained interest.",
        "evidence_gap": "[UNRESOLVED_ITEM: Literature evidence gap requires human knowledge of current evidence base]",
        "objective_statement": "This study aimed to compare primary outcomes between Group A and Group B.",
    },
    "methods": {
        "study_design": (
            "A retrospective cohort study design was used. "
            "The primary statistical test was independent_samples_t_test "
            "[TRACE: statistical_results.method_id]. "
        ),
        "statistical_analysis": (
            "All analyses were performed using R (≥ 4.3). "
            "An independent samples t-test was applied (t.test, base R). "
            "Cohen's d was computed as the effect size measure. "
            "A two-tailed α = 0.05 significance threshold was applied. "
            "[TRACE: statistical_results.method_id]"
        ),
    },
    "results": {
        "sample_description": (
            "A total of 80 participants were included in the analysis "
            "[TRACE: statistical_results.sample_size]. "
            "Group A: n=40; Group B: n=40 [TRACE: statistical_results.group_summaries]."
        ),
        "primary_outcome": (
            "The primary outcome was significantly higher in Group A than Group B "
            "(p = .034 [TRACE: statistical_results.p_value]; "
            "Cohen's d = 0.52 [TRACE: statistical_results.effect_size]; "
            "95% CI: 0.12 to 0.92 [TRACE: statistical_results.ci_lower / ci_upper]). "
            "Results are shown in Table 1 and Figure 1."
        ),
    },
    "discussion": {
        "principal_findings": (
            "The primary analysis showed a statistically significant difference "
            "(p = .034 [TRACE: statistical_results.p_value]) with a medium effect "
            "(Cohen's d = 0.52 [TRACE: statistical_results.effect_size])."
        ),
        "literature_comparison": "[UNRESOLVED_ITEM: Comparison with existing literature requires human knowledge]",
        "limitations": (
            "This retrospective cohort design cannot establish causality. "
            "Single-centre data may limit generalisability. "
            "[UNRESOLVED_ITEM: Additional limitations require expert assessment]"
        ),
    },
    "conclusions": (
        "Group A demonstrated superior outcomes compared with Group B at 12 months "
        "(p = .034 [TRACE: statistical_results.p_value]). "
        "These findings warrant prospective confirmation."
    ),
    "unresolved_items_additions": [
        "Ethical approval statement",
        "Funding and conflicts of interest disclosure",
    ],
}

_MOCK_LLM_RESPONSE = f"```json\n{json.dumps(_MOCK_MANUSCRIPT_JSON, ensure_ascii=False, indent=2)}\n```"


def _make_stub_llm() -> MagicMock:
    llm = MagicMock()
    llm.provider = "anthropic"
    llm.model = "claude-sonnet-4-6"
    llm.complete = AsyncMock(return_value=_MOCK_LLM_RESPONSE)
    return llm


def _make_stub_policy() -> MagicMock:
    pe = MagicMock()
    pe.enforce_multi = AsyncMock()
    return pe


def _make_stub_schema_registry() -> MagicMock:
    sr = MagicMock()
    sr.validate = MagicMock()
    return sr


def _make_stub_audit() -> MagicMock:
    svc = MagicMock()
    svc.write = AsyncMock()
    return svc


def _make_token(exec_id: str) -> CapabilityToken:
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=exec_id,
        bound_agent_id="reporting",
        bound_step_id="reporting_node",
        granted_scopes=frozenset({
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.REPORT_COMPILE_MANUSCRIPT,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        }),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )


# ---------------------------------------------------------------------------
# Main harness
# ---------------------------------------------------------------------------

async def run_harness() -> None:
    print("=" * 60)
    print("Phase 3 Harness: ReportingAgent LLM+RAG manuscript generation")
    print("=" * 60)

    exec_id = str(uuid.uuid4())
    token = _make_token(exec_id)

    stub_llm = _make_stub_llm()
    reference_library = MarkdownReferenceLibrary(ROOT / "knowledge")

    agent = ReportingAgent(
        policy_engine=_make_stub_policy(),
        schema_registry=_make_stub_schema_registry(),
        audit_service=_make_stub_audit(),
        llm_client=stub_llm,
        reference_library=reference_library,
    )

    # Payload: cohort study, STROBE should be inferred, APA style
    statistical_results = {
        "method_id": "independent_samples_t_test",
        "test_name": "Independent Samples t-test",
        "test_statistic": 2.45,
        "df": 78.0,
        "p_value": 0.034,
        "effect_size": 0.52,
        "effect_size_measure": "Cohen's d",
        "ci_lower": 0.12,
        "ci_upper": 0.92,
        "sample_size": 80,
        "group_summaries": {
            "Group_A": {"n": 40, "mean": 5.8, "sd": 1.2},
            "Group_B": {"n": 40, "mean": 4.6, "sd": 1.3},
        },
    }

    figure_manifest = [
        {
            "figure_id": "fig_box_plot_with_jitter_001",
            "actual_path": "/tmp/figure_fig_box_plot_with_jitter_001.png",
            "format": "png",
            "resolution_dpi": 300,
        }
    ]

    payload = {
        "execution_id": exec_id,
        "intent_object": {
            "objective": "between_group_comparison",
            "outcome_type": "continuous",
            "study_design": "cohort",
            "paired": False,
            "outcome_variables": ["outcome_score"],
            "predictor_variables": ["group"],
            "natural_language_summary": "Compare outcome scores between Group A and Group B",
        },
        "statistical_results": statistical_results,
        "figure_manifest": figure_manifest,
        "target_journal_style": "APA",
    }

    agent_input = AgentInput(
        execution_id=exec_id,
        node_id="reporting_node",
        capability_token=token,
        payload=payload,
        input_schema_ref="cie://schemas/analysis-request.schema.json",
    )

    # --- Run 1: LLM path ---
    print("\n[1] LLM path (APA + STROBE cohort study)")
    result = await agent.run(agent_input)
    assert result.status == "success", f"Expected success, got: {result.status} / {result.error_message}"

    op = result.output_payload
    sections = {s["section_id"]: s for s in op["manuscript_sections"]}

    print(f"    Status:          {result.status}")
    print(f"    Sections:        {list(sections.keys())}")
    print(f"    Word count:      {op['word_count_estimate']}")
    print(f"    Journal style:   {op['journal_style']}")
    print(f"    Checklist ID:    {op['reporting_checklist_status']['checklist_id']}")
    print(f"    Checklist ver:   {op['reporting_checklist_status']['checklist_version']}")
    print(f"    Checklist items: {len(op['reporting_checklist_status']['items'])}")
    print(f"    LLM generated:   {op['manuscript_provenance']['llm_generated']}")
    print(f"    Knowledge refs:  {op['manuscript_provenance']['knowledge_references']}")
    print(f"    Unresolved:      {len(op['unresolved_items'])} items")

    # Assertions
    checklist = op["reporting_checklist_status"]
    assert checklist["checklist_id"] == "STROBE", f"Expected STROBE, got {checklist['checklist_id']}"
    assert checklist["checklist_inferred"] is True
    assert checklist["checklist_version"] == "2007"
    assert op["journal_style"] == "APA"
    assert op["manuscript_provenance"]["llm_generated"] is True
    assert len(op["unresolved_items"]) > 0
    assert "methods" in sections, "Missing methods section"
    assert "results" in sections, "Missing results section"
    assert "[TRACE:" in sections["methods"]["content"], "No [TRACE:] in methods section"
    assert "[TRACE:" in sections["results"]["content"], "No [TRACE:] in results section"
    assert "word_count_estimate" in op and op["word_count_estimate"] > 0
    assert len(op["table_specifications"]) >= 1

    print("\n    Methods section (excerpt):")
    print("    " + sections["methods"]["content"][:300].replace("\n", "\n    "))
    print("\n    Results section (excerpt):")
    print("    " + sections["results"]["content"][:300].replace("\n", "\n    "))
    print("\n    Unresolved items:")
    for item in op["unresolved_items"]:
        print(f"      - {item}")

    # --- Run 2: template fallback (llm_client=None) ---
    print("\n[2] Template fallback (llm_client=None)")
    agent_nollm = ReportingAgent(
        policy_engine=_make_stub_policy(),
        schema_registry=_make_stub_schema_registry(),
        audit_service=_make_stub_audit(),
        llm_client=None,
        reference_library=None,
    )
    result2 = await agent_nollm.run(agent_input)
    assert result2.status == "success"
    sections2 = {s["section_id"]: s for s in result2.output_payload["manuscript_sections"]}
    assert "[TRACE:" in sections2["methods"]["content"]
    assert "[TRACE:" in sections2["results"]["content"]
    print(f"    Status: {result2.status}")
    print(f"    Sections: {list(sections2.keys())}")
    print(f"    LLM generated: {result2.output_payload['manuscript_provenance']['llm_generated']}")
    print("    [TRACE:] tags present in methods and results: ✓")

    # --- Run 3: p-value formatting per journal style ---
    print("\n[3] P-value formatting per journal style")
    from cie.agents.reporting import ReportingAgent as RA
    cases = [
        ("APA",       0.034,  "p = .034"),
        ("APA",       0.0003, "p < .001"),
        ("AMA",       0.034,  "P = .034"),
        ("AMA",       0.0003, "P < .001"),
        ("VANCOUVER", 0.034,  "p = 0.034"),
        ("VANCOUVER", 0.0003, "p < 0.001"),
    ]
    for style, p, expected in cases:
        got = RA._format_p_value(p, style)
        status = "✓" if got == expected else f"✗ (got {got!r})"
        print(f"    {style:<12} p={p}  →  {got!r}  {status}")
        assert got == expected, f"Style={style} p={p}: expected {expected!r}, got {got!r}"

    # --- Run 4: explicit checklist not overridden ---
    print("\n[4] Explicit reporting_checklist_id=CONSORT not overridden")
    payload_consort = {**payload, "reporting_checklist_id": "CONSORT"}
    ai4 = AgentInput(
        execution_id=exec_id,
        node_id="reporting_node",
        capability_token=token,
        payload=payload_consort,
        input_schema_ref="cie://schemas/analysis-request.schema.json",
    )
    result4 = await agent.run(ai4)
    assert result4.output_payload["reporting_checklist_status"]["checklist_id"] == "CONSORT"
    assert result4.output_payload["reporting_checklist_status"]["checklist_inferred"] is False
    print("    checklist_id=CONSORT preserved ✓, checklist_inferred=False ✓")

    print("\n" + "=" * 60)
    print("Phase 3 harness PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_harness())
