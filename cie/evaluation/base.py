"""CIE Platform — Evaluation base classes.

Implements AP-017 Evaluation Driven Development and AP-009 Verification Before Trust.
Every generated artifact must pass evaluation before it is accepted.

Architecture constraints:
  - BaseEvaluator is read-only: never modifies artifacts.
  - critical check failure zeroes the entire dimension score.
  - advisory checks reduce score proportionally (weight 0.5 each).
  - Passing threshold: weighted_total_score >= 90 AND no critical_failure.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import uuid4


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EvaluationDimension(str, Enum):
    """Evaluation dimensions defined in evaluation/*.yaml.

    Loading order matches evaluation/correctness.yaml, statistical.yaml,
    security.yaml, usability.yaml, regression.yaml.
    """

    CORRECTNESS = "correctness"
    STATISTICAL = "statistical"
    SECURITY = "security"
    USABILITY = "usability"
    REGRESSION = "regression"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Result of a single atomic check (e.g. CC-001).

    Attributes:
        check_id: Canonical check ID matching evaluation YAML definitions
            (e.g. "CC-001", "COR-002-A").
        dimension: Evaluation dimension this check belongs to.
        passed: True if the check passed.
        severity: "critical" -> dimension score zeroed on failure.
                  "advisory" -> score reduced proportionally.
        message: Human-readable explanation of the result.
        actual_value: Optional string representation of the actual value
            that was checked (for traceability in reports).
        expected_value: Optional string representation of what was expected.
    """

    check_id: str
    dimension: EvaluationDimension
    passed: bool
    severity: Literal["critical", "advisory"]
    message: str
    actual_value: str | None = None
    expected_value: str | None = None


@dataclass
class DimensionScore:
    """Aggregated result for one evaluation dimension.

    Attributes:
        dimension: The dimension being scored.
        score: Computed score 0.0-100.0.
        weight_pct: Percentage weight in the overall score (must sum to 100
            across all active dimensions in EvaluationReport).
        check_results: Ordered list of individual CheckResult objects.
        critical_failure: True if any critical check failed.
            When True, score is always 0.0.
    """

    dimension: EvaluationDimension
    score: float
    weight_pct: int
    check_results: list[CheckResult] = field(default_factory=list)
    critical_failure: bool = False

    def __post_init__(self) -> None:
        if self.score < 0.0 or self.score > 100.0:
            raise ValueError(
                f"DimensionScore.score must be in [0.0, 100.0], got {self.score}"
            )
        if self.weight_pct < 0 or self.weight_pct > 100:
            raise ValueError(
                f"DimensionScore.weight_pct must be in [0, 100], got {self.weight_pct}"
            )


@dataclass
class EvaluationReport:
    """Aggregated evaluation report for a single workflow execution.

    Produced by EvaluatorService after running all registered BaseEvaluator
    instances (correctness, statistical, security, usability).

    Attributes:
        execution_id: Matches the Orchestrator execution_id.
        report_id: Unique UUID for this evaluation run.
        dimension_scores: Mapping from dimension to its DimensionScore.
        weighted_total_score: Weighted average of all dimension scores.
            Weights are read from DimensionScore.weight_pct.
        passed: True iff weighted_total_score >= 90.0 AND no dimension has
            critical_failure=True.  Threshold from correctness.yaml section threshold.
        produced_at: UTC timestamp of evaluation completion.
    """

    execution_id: str
    report_id: str
    dimension_scores: dict[EvaluationDimension, DimensionScore]
    weighted_total_score: float
    passed: bool
    produced_at: datetime

    @classmethod
    def build(
        cls,
        execution_id: str,
        dimension_scores: dict[EvaluationDimension, DimensionScore],
    ) -> "EvaluationReport":
        """Compute weighted_total_score and passed from dimension_scores.

        Args:
            execution_id: Orchestrator execution identifier.
            dimension_scores: Scored dimensions from BaseEvaluator.evaluate().

        Returns:
            Fully populated EvaluationReport.

        Raises:
            ValueError: If weights do not sum to 100 across provided dimensions.
        """
        total_weight = sum(d.weight_pct for d in dimension_scores.values())
        if total_weight != 100:
            raise ValueError(
                f"EvaluationReport: dimension weights must sum to 100, got {total_weight}"
            )

        weighted_total = sum(
            d.score * d.weight_pct / 100.0 for d in dimension_scores.values()
        )
        weighted_total = round(max(0.0, min(100.0, weighted_total)), 4)

        any_critical_failure = any(
            d.critical_failure for d in dimension_scores.values()
        )
        passed = (weighted_total >= 90.0) and (not any_critical_failure)

        return cls(
            execution_id=execution_id,
            report_id=str(uuid4()),
            dimension_scores=dimension_scores,
            weighted_total_score=weighted_total,
            passed=passed,
            produced_at=datetime.utcnow(),
        )


# ---------------------------------------------------------------------------
# Abstract base evaluator
# ---------------------------------------------------------------------------

class BaseEvaluator(ABC):
    """Abstract base class for all CIE evaluation dimensions.

    Subclasses must declare:
        - dimension (property): the EvaluationDimension this covers.
        - weight_pct (property): integer percentage weight.
        - evaluate(artifacts): return a DimensionScore.

    Subclasses must NOT:
        - modify any artifact passed to evaluate().
        - make network requests.
        - depend on runtime implementation details.
    """

    @property
    @abstractmethod
    def dimension(self) -> EvaluationDimension:
        """The evaluation dimension this evaluator covers."""
        ...

    @property
    @abstractmethod
    def weight_pct(self) -> int:
        """Percentage weight in the overall score (0-100)."""
        ...

    @abstractmethod
    def evaluate(self, artifacts: dict) -> DimensionScore:
        """Run all checks for this dimension and return a DimensionScore.

        Args:
            artifacts: Dict of artifact keys to their values.
                Common keys: "execution_result", "review_report",
                "analysis_plan", "figure_manifest", "manuscript_sections".
                Missing keys must result in a DimensionScore with score=0.0
                and an explanatory CheckResult (not an exception).

        Returns:
            DimensionScore populated from check results.
        """
        ...

    def _pass_score(self, check_results: list[CheckResult]) -> float:
        """Compute dimension score from a list of CheckResult objects.

        Scoring rules (evaluation/correctness.yaml section scoring):
            1. Any critical check failure -> return 0.0 immediately.
            2. Each failed advisory check deducts (50 / total_advisory) points.
               advisory_check_weight = 0.5 means advisory band contributes
               at most 50 pts; each failure deducts an equal share.
            3. Score is clipped to [0.0, 100.0].

        Args:
            check_results: List of CheckResult objects for this dimension.

        Returns:
            Float score in [0.0, 100.0].
        """
        # Rule 1: any critical failure zeros the entire dimension
        if any(r.severity == "critical" and not r.passed for r in check_results):
            return 0.0

        advisory_results = [r for r in check_results if r.severity == "advisory"]
        total_advisory = len(advisory_results)

        if total_advisory == 0:
            # No advisory checks exist: all criticals passed -> perfect score
            return 100.0

        failed_advisory = sum(1 for r in advisory_results if not r.passed)

        # Each advisory failure deducts an equal share of the 50-point advisory band
        deduction = (failed_advisory / total_advisory) * 50.0

        return max(0.0, min(100.0, 100.0 - deduction))
