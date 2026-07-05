"""Phase 7(C) Verification Harness — Continuation Analysis Loop.

Usage:
    cd /path/to/Clinical\ insight\ engine
    python3 scratchpad/harness_continuation_exec.py

Verifies the full continuation pipeline:
  1. Primary analysis (StatisticsAgent → RuntimeAgent) — establishes prior results
  2. Continuation analysis (StatisticsAgent with continuation_query + prior context
     → RuntimeAgent) — follow-up R script executed with real Rscript
  3. Continuation visualization (VisualizationAgent with prior_statistical_results)
     → real PNG generated

Checks:
  A. Primary statistical_results parsed from real result.json
  B. Continuation R script uses _R_CONTINUATION_SYSTEM_PROMPT (provenance["continuation"]=True)
  C. Continuation statistical_results present (new p-value from result.json)
  D. VisualizationAgent caption_draft carries is_continuation=True
  E. Continuation PNG exists on disk

Requires: Rscript in PATH with jsonlite installed.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
_log = logging.getLogger("harness_continuation")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Stub LLM R scripts
# ---------------------------------------------------------------------------

# Primary analysis: independent t-test (same as full DAG harness)
_PRIMARY_R = r"""
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
cat("primary_result_written\n")
"""

# Continuation analysis: Mann-Whitney U (follow-up — non-parametric)
_CONTINUATION_R = r"""
set.seed(42)
# Continuation: Mann-Whitney U as non-parametric follow-up to the prior t-test
# (Prior: t-test p=0.014, Cohen's d=0.65 — checking with non-parametric approach)
data <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"), "dataset.csv"),
                 stringsAsFactors = TRUE)

wt <- wilcox.test(sbp_mmhg ~ group, data = data, conf.int = TRUE)
g  <- split(data$sbp_mmhg, data$group)
n1 <- length(g[[1]]); n2 <- length(g[[2]])

# Rank-biserial correlation as effect size
r_rb <- 1 - 2 * wt$statistic / (n1 * n2)

result <- list(
  method_id = "mann_whitney_u_test",
  test_name = "Mann-Whitney U Test (Wilcoxon rank-sum)",
  test_statistic = unname(wt$statistic),
  df = NULL,
  p_value = wt$p.value,
  effect_size = unname(abs(r_rb)),
  effect_size_measure = "rank-biserial r",
  ci_lower = wt$conf.int[1],
  ci_upper = wt$conf.int[2],
  sample_size = nrow(data),
  group_summaries = lapply(g, function(x)
    list(n = length(x), median = median(x), iqr = IQR(x)))
)
writeLines(jsonlite::toJSON(result, auto_unbox = TRUE, digits = 10),
           file.path(Sys.getenv("OUTPUT_DIR"), "result.json"))
cat("continuation_result_written\n")
"""

# Visualization R for continuation
_CONT_VIZ_R = r"""
set.seed(42)
library(ggplot2)
data <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"), "dataset.csv"),
                 stringsAsFactors = FALSE)

p <- ggplot(data, aes(x = group, y = sbp_mmhg, fill = group)) +
  geom_boxplot(outlier.shape = NA, alpha = 0.7) +
  geom_jitter(width = 0.15, alpha = 0.5, size = 1.5, colour = "grey40") +
  scale_fill_manual(values = c("#009E73", "#D55E00")) +
  theme_classic() +
  labs(x = "Group", y = "SBP (mmHg)",
       title = "Follow-up: Non-parametric Comparison",
       caption = "Mann-Whitney U (continuation analysis)")

out_path <- file.path(Sys.getenv("OUTPUT_DIR"), "figure_fig_box_plot_continuation_001.png")
ggsave(out_path, plot = p, width = 180, height = 120, units = "mm", dpi = 150)
cat(sprintf("continuation_figure_saved: %s\n", out_path))
"""


def _stub_llm_seq(scripts: list[str]) -> MagicMock:
    """Return a stub LLM whose complete() cycles through the provided scripts."""
    responses = iter([f"```r\n{s.strip()}\n```" for s in scripts])

    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=lambda *_a, **_kw: next(responses))
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
        inferred = (
            "continuous" if pd.api.types.is_numeric_dtype(series)
            else "categorical_binary" if series.nunique(dropna=True) <= 2
            else "categorical_nominal"
        )
        metadata[str(col)] = {"inferred_type": inferred,
                               "unique_count": int(series.nunique(dropna=True))}
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
        "dataset_id": "harness_continuation_dataset",
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
# Harness
# ---------------------------------------------------------------------------

async def run_harness() -> bool:
    from cie.agents.base import AgentInput
    from cie.agents.runtime import RuntimeAgent
    from cie.agents.statistics import StatisticsAgent
    from cie.agents.visualization import VisualizationAgent
    from cie.cache.r_script_cache import RScriptCache
    from cie.knowledge.reference_library import MarkdownReferenceLibrary
    from cie.runtime.r_executor import LocalRExecutor
    from cie.runtime.runtime_provider import RuntimeProvider
    from cie.schemas.validator import SchemaRegistry
    from cie.security.capability_token import CapabilityScope, CapabilityTokenManager
    from cie.security.policy_engine import PolicyEngine

    # Temporary directories
    tmp = Path(tempfile.mkdtemp(prefix="cie_continuation_"))
    workspace = tmp / "workspace"
    r_output = tmp / "r_output"
    viz_output = tmp / "viz_output"
    r_scripts = tmp / "r_scripts"
    viz_scripts = tmp / "viz_scripts"
    cache_dir = tmp / "cache"
    for d in (workspace, r_output, viz_output, r_scripts, viz_scripts, cache_dir):
        d.mkdir(parents=True)

    sample_csv = ROOT / "sample_data.csv"
    if not sample_csv.exists():
        _log.error("sample_data.csv not found: %s", sample_csv)
        return False
    shutil.copy(sample_csv, workspace / "dataset.csv")

    # Minimal service stubs
    audit_stub = MagicMock()
    audit_stub.write = AsyncMock()
    token_manager = CapabilityTokenManager()
    policy_engine = PolicyEngine(token_manager, audit_stub)
    schema_registry = SchemaRegistry(schema_dir=ROOT / "schemas")
    guard_stub = MagicMock()
    guard_stub.sanitize_stdout = AsyncMock(side_effect=lambda t, *a, **k: t)

    reference_library = MarkdownReferenceLibrary(ROOT / "knowledge")
    script_cache = RScriptCache(cache_dir=cache_dir)

    # Agents — statistics shares the LLM that returns primary then continuation R
    stats_llm = _stub_llm_seq([_PRIMARY_R, _CONTINUATION_R])
    statistics = StatisticsAgent(
        policy_engine, schema_registry, audit_stub,
        llm_client=stats_llm,
        reference_library=reference_library,
        script_cache=script_cache,
    )

    local_executor = LocalRExecutor(
        workspace_dir=workspace, output_dir=r_output, context_guard=guard_stub
    )
    runtime_provider = RuntimeProvider(local_executor=local_executor)
    runtime_agent = RuntimeAgent(
        policy_engine, schema_registry, audit_stub, runtime_provider,
        workspace_dir=r_scripts, output_dir=r_output,
    )

    viz_executor = LocalRExecutor(
        workspace_dir=workspace, output_dir=viz_output, context_guard=guard_stub
    )
    viz_runtime = RuntimeProvider(local_executor=viz_executor)
    visualization = VisualizationAgent(
        policy_engine, schema_registry, audit_stub,
        llm_client=_stub_llm_seq([_CONT_VIZ_R]),
        reference_library=reference_library,
        script_cache=RScriptCache(cache_dir=cache_dir / "viz"),
        runtime_provider=viz_runtime,
        workspace_dir=viz_scripts,
        output_dir=viz_output,
    )

    dataset_context = _build_dataset_context(sample_csv)
    col_meta = dataset_context["dataset_structural_metadata"]

    passed = True

    def check(cond: bool, label: str) -> None:
        nonlocal passed
        if cond:
            _log.info("PASS: %s", label)
        else:
            _log.error("FAIL: %s", label)
            passed = False

    # ------------------------------------------------------------------
    # Phase A — Primary analysis
    # ------------------------------------------------------------------
    _log.info("=== Phase A: Primary analysis ===")
    exec_id_primary = f"harness-primary-{uuid.uuid4().hex[:8]}"

    tok_stat = token_manager.issue(
        exec_id_primary, "statistics", "primary_statistics",
        {CapabilityScope.DATASET_READ_VALIDATED,
         CapabilityScope.R_CODE_GENERATE_TEMPLATE,
         CapabilityScope.AUDIT_WRITE_ENTRY},
    )
    try:
        stat_input = AgentInput(
            execution_id=exec_id_primary,
            node_id="primary_statistics",
            capability_token=tok_stat,
            payload={
                "data_quality_report": {"quality_gate_passed": True},
                "intent_object": _INTENT,
                "dataset_structural_metadata": col_meta,
                "inject_raw_data_rows": False,
            },
            input_schema_ref="cie://schemas/task-context.schema.json",
        )
        stat_out = await statistics.run(stat_input)
    finally:
        token_manager.revoke(tok_stat)

    check(stat_out.status == "success", "Primary StatisticsAgent success")
    primary_r_script = stat_out.output_payload.get("r_script", "")
    check(bool(primary_r_script), "Primary r_script generated")
    check(not stat_out.output_payload.get("r_script_provenance", {}).get("continuation", False),
          "Primary provenance.continuation=False (fresh analysis)")

    # Runtime execution for primary
    tok_rt = token_manager.issue(
        exec_id_primary, "runtime", "primary_runtime",
        {CapabilityScope.RUNTIME_INVOKE_EXECUTION, CapabilityScope.AUDIT_WRITE_ENTRY},
    )
    try:
        rt_input = AgentInput(
            execution_id=exec_id_primary,
            node_id="primary_runtime",
            capability_token=tok_rt,
            payload={"r_script": primary_r_script, "inject_raw_data_rows": False},
            input_schema_ref="cie://schemas/task-context.schema.json",
        )
        rt_out = await runtime_agent.run(rt_input)
    finally:
        token_manager.revoke(tok_rt)

    check(rt_out.status == "success", "Primary RuntimeAgent success")
    prior_sr = rt_out.output_payload.get("statistical_results")
    if prior_sr:
        _log.info("Primary: p=%.4g, d=%.3f", prior_sr.get("p_value"), prior_sr.get("effect_size"))
    check(bool(prior_sr) and prior_sr.get("p_value") is not None,
          "Primary statistical_results parsed from real result.json")

    # ------------------------------------------------------------------
    # Phase B — Continuation analysis
    # ------------------------------------------------------------------
    _log.info("=== Phase B: Continuation analysis (Mann-Whitney follow-up) ===")
    exec_id_cont = f"harness-cont-{uuid.uuid4().hex[:8]}"
    continuation_query = "ノンパラメトリック検定（Mann-Whitney U）で確認したい"

    tok_cont_stat = token_manager.issue(
        exec_id_cont, "statistics", "continuation_statistics",
        {CapabilityScope.DATASET_READ_VALIDATED,
         CapabilityScope.R_CODE_GENERATE_TEMPLATE,
         CapabilityScope.AUDIT_WRITE_ENTRY},
    )
    try:
        cont_stat_input = AgentInput(
            execution_id=exec_id_cont,
            node_id="continuation_statistics",
            capability_token=tok_cont_stat,
            payload={
                "data_quality_report": {"quality_gate_passed": True},
                "intent_object": _INTENT,
                "dataset_structural_metadata": col_meta,
                "continuation_query": continuation_query,
                "prior_statistical_results": prior_sr,
                "prior_r_script": primary_r_script,
                "inject_raw_data_rows": False,
            },
            input_schema_ref="cie://schemas/task-context.schema.json",
        )
        cont_stat_out = await statistics.run(cont_stat_input)
    finally:
        token_manager.revoke(tok_cont_stat)

    check(cont_stat_out.status == "success", "Continuation StatisticsAgent success")
    cont_r_script = cont_stat_out.output_payload.get("r_script", "")
    check(bool(cont_r_script), "Continuation r_script generated")
    prov = cont_stat_out.output_payload.get("r_script_provenance", {})
    check(prov.get("continuation") is True, "Continuation provenance.continuation=True")
    check(prov.get("llm_generated") is True, "Continuation provenance.llm_generated=True")

    # Runtime execution for continuation
    tok_cont_rt = token_manager.issue(
        exec_id_cont, "runtime", "continuation_runtime",
        {CapabilityScope.RUNTIME_INVOKE_EXECUTION, CapabilityScope.AUDIT_WRITE_ENTRY},
    )
    try:
        cont_rt_input = AgentInput(
            execution_id=exec_id_cont,
            node_id="continuation_runtime",
            capability_token=tok_cont_rt,
            payload={"r_script": cont_r_script, "inject_raw_data_rows": False},
            input_schema_ref="cie://schemas/task-context.schema.json",
        )
        cont_rt_out = await runtime_agent.run(cont_rt_input)
    finally:
        token_manager.revoke(tok_cont_rt)

    check(cont_rt_out.status == "success", "Continuation RuntimeAgent success")
    cont_sr = cont_rt_out.output_payload.get("statistical_results")
    if cont_sr:
        _log.info("Continuation: method=%s p=%.4g effect=%.3f",
                  cont_sr.get("method_id"),
                  cont_sr.get("p_value"),
                  cont_sr.get("effect_size"))
    check(bool(cont_sr) and cont_sr.get("p_value") is not None,
          "Continuation statistical_results parsed from real result.json")
    check(cont_sr.get("method_id") == "mann_whitney_u_test" if cont_sr else False,
          "Continuation method_id=mann_whitney_u_test")

    # ------------------------------------------------------------------
    # Phase C — Continuation Visualization
    # ------------------------------------------------------------------
    _log.info("=== Phase C: Continuation Visualization ===")

    tok_viz = token_manager.issue(
        exec_id_cont, "visualization", "continuation_visualization",
        {CapabilityScope.DATASET_READ_VALIDATED,
         CapabilityScope.R_CODE_GENERATE_TEMPLATE,
         CapabilityScope.AUDIT_WRITE_ENTRY,
         CapabilityScope.RUNTIME_INVOKE_EXECUTION},
    )
    try:
        viz_input = AgentInput(
            execution_id=exec_id_cont,
            node_id="continuation_visualization",
            capability_token=tok_viz,
            payload={
                "statistical_results": cont_sr,
                "intent_object": _INTENT,
                "dataset_structural_metadata": col_meta,
                "prior_statistical_results": prior_sr,
                "continuation_query": continuation_query,
                "inject_raw_data_rows": False,
            },
            input_schema_ref="cie://schemas/task-context.schema.json",
        )
        viz_out = await visualization.run(viz_input)
    finally:
        token_manager.revoke(tok_viz)

    check(viz_out.status == "success", "Continuation VisualizationAgent success")
    specs = viz_out.output_payload.get("visualization_specifications", [])
    caption = specs[0].get("caption_draft", {}) if specs else {}
    check(caption.get("is_continuation") is True,
          "caption_draft.is_continuation=True")
    check(caption.get("prior_method_id") == "independent_samples_t_test",
          f"caption_draft.prior_method_id=independent_samples_t_test "
          f"(got {caption.get('prior_method_id')})")

    manifest = viz_out.output_payload.get("figure_manifest") or []
    actual_paths = [e.get("actual_path") for e in manifest if isinstance(e, dict)]
    real_pngs = [p for p in actual_paths if p and Path(p).exists()]
    check(bool(real_pngs), f"Continuation PNG on disk: {real_pngs}")

    _log.info("Harness result: %s", "PASSED" if passed else "FAILED")
    _log.info("Tmp artefacts: %s", tmp)
    return passed


if __name__ == "__main__":
    ok = asyncio.run(run_harness())
    sys.exit(0 if ok else 1)
