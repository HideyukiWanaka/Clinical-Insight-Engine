"""Phase 6 Verification Harness — Full DAG E2E with the real Orchestrator.

Usage:
    cd /path/to/Clinical\ insight\ engine
    python3 scratchpad/harness_full_dag_exec.py

Drives the real Orchestrator + real agents through the complete
clinical_analysis_standard DAG:

  intake(skipped: precomputed intent)
  → validate_dataset/classify_variables/detect_missing/detect_outliers (real DataQualityAgent)
  → select_analysis → assumption_check (real StatisticsAgent, stub LLM)
  → decision_assumption (rules routing: normality=true → generate_r_script)
  → generate_r_script (stub LLM returns a real t-test R script)
  → security_review (approval → WAITING_FOR_HUMAN)
  → [resume_workflow]
  → runtime_execution (REAL Rscript → result.json → statistical_results)
  → visualization (stub LLM ggplot2 → REAL PNG)
  → reporting (template fallback manuscript)
  → reviewer → evaluation (real EvaluationAgent, 4 dimensions)

Verifies:
  1. run_workflow suspends at security_review (waiting_for_human)
  2. decision_assumption routed to generate_r_script; select_nonparametric pruned
  3. resume_workflow completes the DAG (final_state=completed)
  4. statistical_results parsed from the real result.json (p_value etc.)
  5. figure_manifest points at a real PNG on disk
  6. evaluation node produced evaluation_report + completion_status

Requires: Rscript in PATH with ggplot2 + jsonlite installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
_log = logging.getLogger("harness_full_dag")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Stub LLM outputs — real executable R
# ---------------------------------------------------------------------------

_STATS_R = r"""
set.seed(42)
data <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"), "dataset.csv"),
                 stringsAsFactors = TRUE)

tt <- t.test(sbp_mmhg ~ group, data = data)
g  <- split(data$sbp_mmhg, data$group)

n1 <- length(g[[1]]); n2 <- length(g[[2]])
sd_pooled <- sqrt(((n1 - 1) * var(g[[1]]) + (n2 - 1) * var(g[[2]])) / (n1 + n2 - 2))
cohens_d  <- abs(mean(g[[1]]) - mean(g[[2]])) / sd_pooled

result <- list(
  method_id = "independent_samples_t_test",
  test_name = "Welch Two Sample t-test",
  test_statistic = unname(tt$statistic),
  df = unname(tt$parameter),
  p_value = tt$p.value,
  effect_size = unname(cohens_d),
  effect_size_measure = "cohens_d",
  ci_lower = tt$conf.int[1],
  ci_upper = tt$conf.int[2],
  sample_size = nrow(data),
  group_summaries = lapply(g, function(x)
    list(n = length(x), mean = mean(x), sd = sd(x)))
)

writeLines(jsonlite::toJSON(result, auto_unbox = TRUE, digits = 10),
           file.path(Sys.getenv("OUTPUT_DIR"), "result.json"))
cat("result_written\n")
"""

_VIZ_R = r"""
set.seed(42)
library(ggplot2)

data <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"), "dataset.csv"),
                 stringsAsFactors = FALSE)

p <- ggplot(data, aes(x = group, y = sbp_mmhg, fill = group)) +
  geom_boxplot(outlier.shape = NA, alpha = 0.7) +
  geom_jitter(width = 0.15, alpha = 0.5, size = 1.5, colour = "grey40") +
  scale_fill_manual(values = c("#E69F00", "#56B4E9")) +
  theme_classic() +
  labs(x = "Group", y = "SBP (mmHg)", title = "Group Comparison")

out_path <- file.path(Sys.getenv("OUTPUT_DIR"), "figure_fig_box_plot_001.png")
ggsave(out_path, plot = p, width = 180, height = 120, units = "mm", dpi = 150)
cat(sprintf("figure_saved: %s\n", out_path))
"""


def _stub_llm(r_code: str) -> MagicMock:
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=f"```r\n{r_code.strip()}\n```")
    llm.provider = "stub"
    llm.model = "stub-model"
    return llm


# ---------------------------------------------------------------------------
# Dataset context (mirrors cie.ui.app._build_dataset_context)
# ---------------------------------------------------------------------------

def _build_dataset_context(csv_path: Path) -> dict:
    import pandas as pd

    df = pd.read_csv(csv_path)
    row_count = int(len(df))
    metadata: dict = {}
    dq_columns: list[dict] = []
    alias_map: dict[str, str] = {}
    for idx, col in enumerate(df.columns, start=1):
        series = df[col]
        if pd.api.types.is_numeric_dtype(series):
            inferred = "continuous"
        elif series.nunique(dropna=True) <= 2:
            inferred = "categorical_binary"
        else:
            inferred = "categorical_nominal"
        metadata[str(col)] = {
            "inferred_type": inferred,
            "unique_count": int(series.nunique(dropna=True)),
        }
        var_n = f"var_{idx}"
        alias_map[var_n] = str(col)
        missing = int(series.isna().sum())
        dq_columns.append({
            "var_n": var_n,
            "inferred_type": inferred,
            "missing_count": missing,
            "missing_rate_pct": round(missing / row_count * 100.0, 2) if row_count else 0.0,
        })

    return {
        "dataset_structural_metadata": metadata,
        "data_quality_report": {"quality_gate_passed": True},
        "dataset_id": "harness_dataset",
        "metadata_type": "validated_structural",
        "row_count": row_count,
        "column_count": len(dq_columns),
        "columns": dq_columns,
        "var_n_alias_map": alias_map,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


_INTENT = {
    "objective": "between_group_comparison",
    "outcome_type": "continuous",
    "paired": False,
    "distribution_assumptions": "assumed_normal",
    "outcome_variables": ["sbp_mmhg"],
    "predictor_variables": ["group"],
    "requires_human_clarification": False,
}


# ---------------------------------------------------------------------------
# Main harness
# ---------------------------------------------------------------------------

async def run_harness() -> bool:
    from cie.agents.data_quality import DataQualityAgent
    from cie.agents.evaluation import EvaluationAgent
    from cie.agents.reporting import ReportingAgent
    from cie.agents.reviewer import ReviewerAgent
    from cie.agents.runtime import RuntimeAgent
    from cie.agents.statistics import StatisticsAgent
    from cie.agents.visualization import VisualizationAgent
    from cie.cache.r_script_cache import RScriptCache
    from cie.knowledge.reference_library import MarkdownReferenceLibrary
    from cie.runtime.r_executor import LocalRExecutor
    from cie.runtime.runtime_provider import RuntimeProvider
    from cie.schemas.validator import SchemaRegistry
    from cie.security.capability_token import CapabilityTokenManager
    from cie.security.pii_filter import PIIFilter
    from cie.security.policy_engine import PolicyEngine
    from cie.workflow.orchestrator import Orchestrator
    from cie.workflow.registry import WorkflowRegistry
    from cie.workflow.states import WorkflowStateMachine

    # --- Tmp dirs ---
    tmp_base = Path(tempfile.mkdtemp(prefix="cie_full_dag_"))
    workspace = tmp_base / "workspace"
    r_output = tmp_base / "r_output"
    viz_output = tmp_base / "viz_output"
    for d in (workspace, r_output, viz_output, tmp_base / "r_scripts",
              tmp_base / "viz_scripts", tmp_base / "cache"):
        d.mkdir(parents=True)

    sample_csv = ROOT / "sample_data.csv"
    if not sample_csv.exists():
        _log.error("sample_data.csv not found: %s", sample_csv)
        return False
    shutil.copy(sample_csv, workspace / "dataset.csv")

    # --- Real security / schema / audit(stub) plumbing ---
    audit_stub = MagicMock()
    audit_stub.write = AsyncMock()
    token_manager = CapabilityTokenManager()
    policy_engine = PolicyEngine(token_manager, audit_stub)
    schema_registry = SchemaRegistry(schema_dir=ROOT / "schemas")
    guard_stub = MagicMock()
    guard_stub.sanitize_stdout = AsyncMock(side_effect=lambda t, *a, **k: t)

    reference_library = MarkdownReferenceLibrary(ROOT / "knowledge")
    script_cache = RScriptCache(cache_dir=tmp_base / "cache")

    # --- Real agents ---
    data_quality = DataQualityAgent(policy_engine, schema_registry, audit_stub, PIIFilter())
    statistics = StatisticsAgent(
        policy_engine, schema_registry, audit_stub,
        llm_client=_stub_llm(_STATS_R),
        reference_library=reference_library,
        script_cache=script_cache,
    )
    runtime_agent = RuntimeAgent(
        policy_engine, schema_registry, audit_stub,
        RuntimeProvider(local_executor=LocalRExecutor(
            workspace_dir=workspace, output_dir=r_output, context_guard=guard_stub,
        )),
        workspace_dir=tmp_base / "r_scripts",
        output_dir=r_output,
    )
    visualization = VisualizationAgent(
        policy_engine, schema_registry, audit_stub,
        llm_client=_stub_llm(_VIZ_R),
        reference_library=reference_library,
        script_cache=script_cache,
        runtime_provider=RuntimeProvider(local_executor=LocalRExecutor(
            workspace_dir=workspace, output_dir=viz_output, context_guard=guard_stub,
        )),
        workspace_dir=tmp_base / "viz_scripts",
        output_dir=viz_output,
    )
    reporting = ReportingAgent(
        policy_engine, schema_registry, audit_stub,
        llm_client=None,  # template fallback keeps the harness API-free
        reference_library=reference_library,
    )
    reviewer = ReviewerAgent(policy_engine, schema_registry, audit_stub)
    evaluation = EvaluationAgent(policy_engine, schema_registry, audit_stub)

    orchestrator = Orchestrator(
        workflow_registry=WorkflowRegistry.load_from_yaml(ROOT / "spec" / "workflow.yaml"),
        state_machine=WorkflowStateMachine(),
        token_manager=token_manager,
        policy_engine=policy_engine,
        context_guard=guard_stub,
        audit_service=audit_stub,
        agent_registry={
            "data_quality": data_quality,
            "statistics": statistics,
            "runtime": runtime_agent,
            "visualization": visualization,
            "reporting": reporting,
            "reviewer": reviewer,
            "evaluation": evaluation,
        },
    )

    execution_id = f"harness-full-dag-{uuid.uuid4().hex[:8]}"
    dataset_context = _build_dataset_context(sample_csv)

    passed = True

    def check(cond: bool, label: str) -> None:
        nonlocal passed
        if cond:
            _log.info("PASS: %s", label)
        else:
            _log.error("FAIL: %s", label)
            passed = False

    # --- Phase A: run until the security_review approval gate ---
    _log.info("=== run_workflow (until security_review) ===")
    result = await orchestrator.run_workflow(
        execution_id, _INTENT, dataset_context=dataset_context
    )
    node_ids = [r.node_id for r in result["node_results"]]
    _log.info("dispatched: %s (final_state=%s)", node_ids, result["final_state"])

    check(result["workflow_id_selected"] == "clinical_analysis_standard",
          "WS-004 selected clinical_analysis_standard")
    check(result["final_state"] == "waiting_for_human",
          "suspended at security_review (waiting_for_human)")
    check("generate_r_script" in node_ids, "generate_r_script dispatched")
    check("select_nonparametric" not in node_ids,
          "select_nonparametric pruned by decision_assumption")
    statuses = {r.node_id: r.status for r in result["node_results"]}
    check(statuses.get("security_review") == "waiting_for_human",
          "security_review is the waiting node")

    r_script = ""
    for r in result["node_results"]:
        if r.output_payload.get("r_script"):
            r_script = r.output_payload["r_script"]
    check(bool(r_script) and "set.seed(42)" in r_script,
          "generated R script present for human review")

    # --- Phase B: human approves → resume to completion ---
    _log.info("=== resume_workflow (approved) ===")
    resume = await orchestrator.resume_workflow(
        execution_id,
        {"execution_permission": True,
         "human_decision": {"decision": "approved", "node_id": "security_review"}},
    )
    resumed_ids = [r.node_id for r in resume["node_results"]]
    _log.info("resumed: %s (final_state=%s)", resumed_ids, resume["final_state"])
    for r in resume["node_results"]:
        if r.status != "completed":
            _log.error("node %s status=%s error=%s", r.node_id, r.status, r.error_code)

    check(resume["final_state"] == "completed", "DAG completed after resume")
    for node in ("runtime_execution", "visualization", "reporting", "reviewer", "evaluation"):
        check(node in resumed_ids, f"{node} dispatched after resume")

    outputs = {r.node_id: r.output_payload for r in resume["node_results"]}

    # Runtime: real statistical_results from result.json
    stats = (outputs.get("runtime_execution") or {}).get("statistical_results")
    if stats:
        _log.info("statistical_results: p=%.3g d=%.3f CI=[%.2f, %.2f] n=%s",
                  stats.get("p_value"), stats.get("effect_size"),
                  stats.get("ci_lower"), stats.get("ci_upper"), stats.get("sample_size"))
    check(bool(stats) and stats.get("p_value") is not None,
          "statistical_results parsed from real result.json")

    # Visualization: real PNG on disk
    manifest = (outputs.get("visualization") or {}).get("figure_manifest") or []
    actual_paths = [e.get("actual_path") for e in manifest if isinstance(e, dict)]
    real_pngs = [p for p in actual_paths if p and Path(p).exists()]
    check(bool(real_pngs), f"figure_manifest points at a real PNG ({real_pngs})")

    # Reporting: manuscript sections produced
    sections = (outputs.get("reporting") or {}).get("manuscript_sections") or []
    check(bool(sections), f"manuscript_sections produced ({len(sections)} sections)")

    # Reviewer output
    check("review_passed" in (outputs.get("reviewer") or {}), "reviewer produced review result")

    # Evaluation node output
    ev = outputs.get("evaluation") or {}
    report = ev.get("evaluation_report") or {}
    check(bool(report), "evaluation_report produced")
    check(ev.get("completion_status") in {"passed", "failed"},
          f"completion_status={ev.get('completion_status')} "
          f"(score={ev.get('evaluation_score')})")
    if report:
        _log.info("evaluation dimensions: %s",
                  {k: v["score"] for k, v in report.get("dimension_scores", {}).items()})
    check(bool(ev.get("reproducibility_report", {}).get("set_seed_present")),
          "reproducibility_report.set_seed_present")

    _log.info("Harness result: %s", "PASSED" if passed else "FAILED")
    _log.info("Tmp dir (inspect artefacts): %s", tmp_base)
    return passed


if __name__ == "__main__":
    ok = asyncio.run(run_harness())
    sys.exit(0 if ok else 1)
