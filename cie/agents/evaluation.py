"""CIE Platform — Evaluation Agent.

Executes the evaluation stage of the workflow DAG (spec/workflow.yaml
``evaluation`` node) by running the four registered evaluation dimensions
(cie/evaluation/*: correctness 40% / statistical 35% / security 15% /
usability 10%) against the artifacts accumulated by the upstream nodes.

Design constraints:
  - Read-only: artifacts are never modified (BaseEvaluator contract).
  - No fabrication: every value fed to the evaluators is passed through from
    the accumulated context (ultimately from the real R ``result.json``).
    The agent only *reshapes* keys to the evaluator artifact contract; it
    never invents statistics.
  - Works without a database: EvaluationReport is built in-process via
    ``EvaluationReport.build``. Persisting SkillPerformanceRecord remains
    EvaluatorService's job and is out of scope for this agent.
"""

from __future__ import annotations

import logging
import re

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.audit import AuditService
from cie.evaluation.base import BaseEvaluator, EvaluationReport
from cie.evaluation.correctness import CorrectnessEvaluator
from cie.evaluation.security import SecurityEvaluator
from cie.evaluation.statistical import StatisticalEvaluator
from cie.evaluation.usability import UsabilityEvaluator
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import CapabilityScope
from cie.security.policy_engine import PolicyEngine

_log = logging.getLogger(__name__)

# Effect-size measures whose magnitude maps onto the Cohen's d benchmark
# labels used by CC-007 / ST-004. Other measures (odds ratios, r, etc.) get
# no derived interpretation — deriving one would be dishonest.
_COHEN_D_MEASURES = frozenset({"cohens_d", "cohen_d", "cohen's d", "hedges_g", "hedges' g"})

_SET_SEED_PATTERN = re.compile(r"set\.seed\s*\(")


def _cohen_d_interpretation(value: float) -> str:
    """Standard Cohen's d magnitude labels (same thresholds as ST-004)."""
    magnitude = abs(value)
    if magnitude < 0.2:
        return "negligible"
    if magnitude < 0.5:
        return "small"
    if magnitude < 0.8:
        return "medium"
    return "large"


class EvaluationAgent(BaseAgent):
    """Runs all evaluation dimensions as the final DAG stage.

    Args:
        policy_engine: Enforces capability scope checks.
        schema_registry: Validates input and output payloads.
        audit_service: Records execution outcomes.
        evaluators: Override the default evaluator set (weights must sum to
            100). Defaults to correctness/statistical/security/usability.
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        schema_registry: SchemaRegistry,
        audit_service: AuditService,
        evaluators: list[BaseEvaluator] | None = None,
    ) -> None:
        super().__init__(policy_engine, schema_registry, audit_service)
        self._evaluators: list[BaseEvaluator] = evaluators or [
            CorrectnessEvaluator(),
            StatisticalEvaluator(),
            SecurityEvaluator(),
            UsabilityEvaluator(),
        ]
        total_weight = sum(e.weight_pct for e in self._evaluators)
        if total_weight != 100:
            raise ValueError(
                f"EvaluationAgent: evaluator weights must sum to 100, got {total_weight}."
            )

    @property
    def agent_id(self) -> str:
        return "evaluation"

    @property
    def input_schema_ref(self) -> str:
        return "cie://schemas/task-context.schema.json"

    @property
    def output_schema_ref(self) -> str:
        return "cie://schemas/task-context.schema.json"

    @property
    def required_scopes(self) -> list[CapabilityScope]:
        return [
            CapabilityScope.WORKFLOW_STATE_READ,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ]

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        """Adapt the accumulated context and run every evaluator.

        Steps:
          1. Reshape accumulated context keys into the evaluator artifact
             contract (see ``_build_artifacts``).
          2. Run each evaluator; an evaluator exception yields a zeroed
             critical-failure DimensionScore instead of aborting the node.
          3. Build the EvaluationReport (weighted score, pass >= 90).
          4. Return evaluation_report / reproducibility_report /
             completion_status (spec/workflow.yaml evaluation node outputs).
        """
        payload = agent_input.payload
        artifacts = self._build_artifacts(payload)

        dimension_scores = {}
        for evaluator in self._evaluators:
            try:
                score = evaluator.evaluate(artifacts)
            except Exception as exc:  # noqa: BLE001 — zero the dimension, don't abort
                from cie.evaluation.base import CheckResult, DimensionScore

                _log.error(
                    "Evaluator %s raised: %s", type(evaluator).__name__, exc, exc_info=True
                )
                score = DimensionScore(
                    dimension=evaluator.dimension,
                    score=0.0,
                    weight_pct=evaluator.weight_pct,
                    check_results=[
                        CheckResult(
                            check_id=f"{evaluator.dimension.value.upper()}-EXCEPTION",
                            dimension=evaluator.dimension,
                            passed=False,
                            severity="critical",
                            message=f"Evaluator raised an unexpected exception: {exc}",
                        )
                    ],
                    critical_failure=True,
                )
            dimension_scores[evaluator.dimension] = score

        report = EvaluationReport.build(
            execution_id=agent_input.execution_id,
            dimension_scores=dimension_scores,
        )

        r_script: str = artifacts.get("r_script_content") or ""
        reproducibility_report = {
            "r_script_present": bool(r_script),
            "set_seed_present": bool(_SET_SEED_PATTERN.search(r_script)),
            "statistical_results_present": bool(payload.get("statistical_results")),
            "figure_count": len(artifacts.get("figure_manifest") or []),
        }

        output_payload: dict = {
            "execution_id": agent_input.execution_id,
            "evaluation_report": self._serialize_report(report),
            "reproducibility_report": reproducibility_report,
            "completion_status": "passed" if report.passed else "failed",
            "evaluation_passed": report.passed,
            "evaluation_score": report.weighted_total_score,
        }

        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status="success",
            output_payload=output_payload,
            output_schema_ref=self.output_schema_ref,
        )

    # ------------------------------------------------------------------
    # Context → evaluator artifact adaptation
    # ------------------------------------------------------------------

    def _build_artifacts(self, payload: dict) -> dict:
        """Reshape the accumulated workflow context into evaluator artifacts.

        The evaluators (written against the r_executor-era contract) expect
        ``execution_result.primary_result`` / ``effect_size`` nesting, while
        the RuntimeAgent produces the flat ``statistical_results`` contract
        (method_id, p_value, ci_lower, ...). Every value is passed through
        1:1 — only the shape changes.
        """
        stats: dict = payload.get("statistical_results") or {}

        primary_result = {
            "p_value": stats.get("p_value"),
            "ci_lower": stats.get("ci_lower"),
            "ci_upper": stats.get("ci_upper"),
            "n_observations": stats.get("sample_size"),
        }

        effect_value = stats.get("effect_size")
        measure = str(stats.get("effect_size_measure") or "").strip().lower()
        effect_size: dict = {"value": None, "interpretation": None}
        if isinstance(effect_value, (int, float)):
            # CC-002 checks magnitude (>= 0); direction lives in the CI/sign
            # of the raw statistical_results which remain untouched upstream.
            effect_size["value"] = abs(float(effect_value))
            if measure in _COHEN_D_MEASURES:
                effect_size["interpretation"] = _cohen_d_interpretation(float(effect_value))

        execution_result = {
            "primary_result": primary_result,
            "effect_size": effect_size,
            "method_used": stats.get("method_id") or stats.get("test_name") or "",
        }

        # Reviewer output: review_report + method justification from the
        # Statistics node's selected_methods (CC-005 reads it off review_report).
        review_report: dict = dict(payload.get("review_report") or {})
        selected_methods: list = payload.get("selected_methods") or []
        if "method_justification" not in review_report and selected_methods:
            first = selected_methods[0]
            if isinstance(first, dict) and first.get("justification"):
                review_report["method_justification"] = first["justification"]
        if "unresolved_items" not in review_report:
            review_report["unresolved_items"] = payload.get("unresolved_items") or []

        # Reporting output: list of section dicts → usability contract
        # ({word_count, methods_text}) + flattened text for SEC-006.
        manuscript_sections = payload.get("manuscript_sections")
        manuscript_artifact: dict = {}
        report_content = ""
        if isinstance(manuscript_sections, list):
            texts = [
                str(sec.get("content") or "")
                for sec in manuscript_sections
                if isinstance(sec, dict)
            ]
            report_content = "\n\n".join(texts)
            methods_text = next(
                (
                    str(sec.get("content") or "")
                    for sec in manuscript_sections
                    if isinstance(sec, dict)
                    and str(sec.get("section_id") or "").lower() == "methods"
                ),
                "",
            )
            manuscript_artifact = {
                "word_count": len(report_content.split()),
                "methods_text": methods_text,
            }
        elif isinstance(manuscript_sections, dict):
            manuscript_artifact = manuscript_sections
            report_content = " ".join(
                str(v) for v in manuscript_sections.values() if v
            )

        figure_manifest = payload.get("figure_manifest") or []

        # SEC-002 reads quality_report.pii_checks_performed. DataQualityAgent
        # runs its Layer 1 + Layer 2 PII scan unconditionally in _execute; the
        # presence of its quality_report_section in the context is the
        # evidence that the scan ran (the strict report envelope schema has no
        # slot for the flag itself).
        quality_report: dict = dict(
            payload.get("data_quality_report") or payload.get("quality_report") or {}
        )
        if (
            "pii_checks_performed" not in quality_report
            and payload.get("quality_report_section") is not None
        ):
            quality_report["pii_checks_performed"] = True

        return {
            "execution_result": execution_result,
            "r_script_content": payload.get("r_script") or "",
            "assumption_report": payload.get("assumption_report") or {},
            "analysis_plan": payload.get("analysis_plan") or {},
            "review_report": review_report,
            "quality_report": quality_report,
            "manuscript_sections": manuscript_artifact,
            "figure_manifest": figure_manifest,
            "audit_events": payload.get("audit_events") or [],
            "context_payloads": payload.get("context_payloads") or [],
            "security_report": payload.get("security_report") or {},
            "report_content": report_content,
        }

    @staticmethod
    def _serialize_report(report: EvaluationReport) -> dict:
        """Flatten an EvaluationReport into a JSON-serializable dict."""
        return {
            "report_id": report.report_id,
            "execution_id": report.execution_id,
            "weighted_total_score": report.weighted_total_score,
            "passed": report.passed,
            "produced_at": report.produced_at.isoformat(),
            "dimension_scores": {
                dim.value: {
                    "score": score.score,
                    "weight_pct": score.weight_pct,
                    "critical_failure": score.critical_failure,
                    "checks": [
                        {
                            "check_id": c.check_id,
                            "passed": c.passed,
                            "severity": c.severity,
                            "message": c.message,
                        }
                        for c in score.check_results
                    ],
                }
                for dim, score in report.dimension_scores.items()
            },
        }
