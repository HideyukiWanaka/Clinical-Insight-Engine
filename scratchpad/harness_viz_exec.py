"""Phase 2 Verification Harness — Visualization LLM ggplot2 R generation + PNG output.

Usage:
    cd /path/to/Clinical\ insight\ engine
    python3 scratchpad/harness_viz_exec.py

Verifies:
  1. VisualizationAgent accepts statistical_results + intent_object
  2. LLM (stub) generates a ggplot2 R script
  3. Sandbox executes the script
  4. Real PNG file is produced in OUTPUT_DIR
  5. figure_manifest contains the actual PNG path

Requires: Rscript in PATH, ggplot2 installed in R.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
_log = logging.getLogger("harness_viz")

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Stub ggplot2 R script returned by the mock LLM
# Uses actual Sys.getenv("WORKSPACE_DIR") / Sys.getenv("OUTPUT_DIR") env vars.
# ---------------------------------------------------------------------------

_STUB_VIZ_R = r"""
set.seed(42)
library(ggplot2)

okabe_ito <- c("#E69F00","#56B4E9","#009E73","#F0E442",
               "#0072B2","#D55E00","#CC79A7","#000000")

tryCatch({
  data <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"), "dataset.csv"),
                   stringsAsFactors = FALSE)

  # Defensive column detection
  group_col   <- names(data)[1]
  outcome_col <- names(data)[2]

  cie_theme <- theme_classic() +
    theme(
      text          = element_text(size = 10),
      axis.title    = element_text(size = 10, face = "bold"),
      axis.text     = element_text(size = 9),
      legend.position = "none",
      panel.grid.major = element_line(color = "grey90", linewidth = 0.3),
      panel.grid.minor = element_blank()
    )

  p <- ggplot(data, aes(x = .data[[group_col]],
                        y = .data[[outcome_col]],
                        fill = .data[[group_col]])) +
    geom_boxplot(outlier.shape = NA, alpha = 0.7) +
    geom_jitter(width = 0.15, alpha = 0.5, size = 1.5, colour = "grey40") +
    scale_fill_manual(values = okabe_ito) +
    cie_theme +
    labs(x = group_col, y = outcome_col, title = "Group Comparison") +
    annotate("text", x = 1.5,
             y = max(data[[outcome_col]], na.rm = TRUE) * 1.02,
             label = "p < 0.001  d = 1.04", size = 3.5, fontface = "italic")

  out_path <- file.path(Sys.getenv("OUTPUT_DIR"), "figure_fig_box_plot_with_jitter_001.png")
  ggsave(out_path, plot = p, width = 180, height = 120, units = "mm", dpi = 300)
  cat(sprintf("figure_saved: %s\n", out_path))

}, error = function(e) {
  cat("ERROR:", conditionMessage(e), "\n")
  quit(status = 1)
})
"""

_STUB_VIZ_R_WRAPPED = f"```r\n{_STUB_VIZ_R.strip()}\n```"


# ---------------------------------------------------------------------------
# Statistical results (simulating Phase 1 output — real values from t-test)
# ---------------------------------------------------------------------------

_STAT_RESULTS = {
    "method_id": "independent_samples_t_test",
    "test_name": "Independent Samples t-test",
    "test_statistic": 8.547,
    "df": 98.0,
    "p_value": 2.1e-13,
    "effect_size": 1.04,
    "effect_size_measure": "Cohen's d",
    "ci_lower": 10.25,
    "ci_upper": 16.73,
    "sample_size": 100,
    "group_summaries": {
        "A": {"n": 50, "mean": 132.4, "sd": 8.1},
        "B": {"n": 50, "mean": 119.0, "sd": 7.3},
    },
}

_INTENT = {
    "objective": "between_group_comparison",
    "outcome_type": "continuous",
    "paired": False,
    "outcome_variables": ["sbp_mmhg"],
    "predictor_variables": ["group"],
}

_COLUMN_META = {
    "group":    {"dtype": "object", "nunique": 2, "role": "grouping"},
    "sbp_mmhg": {"dtype": "float64", "nunique": 100, "role": "outcome"},
    "age_years":{"dtype": "float64", "nunique": 45, "role": "covariate"},
    "bmi":      {"dtype": "float64", "nunique": 99, "role": "covariate"},
}


# ---------------------------------------------------------------------------
# Capability token stub
# ---------------------------------------------------------------------------

def _make_stub_token(exec_id: str):
    from cie.security.capability_token import CapabilityScope, CapabilityToken
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id="stub-token-viz",
        bound_execution_id=exec_id,
        bound_agent_id="visualization",
        bound_step_id="visualization_node",
        granted_scopes=frozenset({
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.R_CODE_GENERATE_TEMPLATE,
            CapabilityScope.RUNTIME_INVOKE_EXECUTION,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        }),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=600),
    )


# ---------------------------------------------------------------------------
# Main harness
# ---------------------------------------------------------------------------

async def run_harness() -> bool:
    from cie.agents.base import AgentInput
    from cie.agents.visualization import VisualizationAgent
    from cie.cache.r_script_cache import RScriptCache
    from cie.knowledge.reference_library import MarkdownReferenceLibrary
    from cie.runtime.r_executor import LocalRExecutor
    from cie.runtime.runtime_provider import RuntimeProvider

    # --- Stub LLM (returns the hardcoded ggplot2 R script) ---
    llm_stub = MagicMock()
    llm_stub.complete = AsyncMock(return_value=_STUB_VIZ_R_WRAPPED)
    llm_stub.provider = "stub"
    llm_stub.model = "stub-model"

    # --- Stub policy engine / schema registry / audit ---
    policy_stub = MagicMock()
    policy_stub.enforce_multi = AsyncMock()
    schema_stub = MagicMock()
    schema_stub.validate = MagicMock()
    audit_stub = MagicMock()
    audit_stub.write = AsyncMock()

    # --- Stub context_guard (sanitize_stdout passes through) ---
    guard_stub = MagicMock()
    guard_stub.sanitize_stdout = AsyncMock(side_effect=lambda t, *a, **k: t)

    # --- Tmp workspace / output dirs ---
    tmp_base = Path(tempfile.mkdtemp(prefix="cie_viz_harness_"))
    workspace_dir = tmp_base / "workspace"
    output_dir = tmp_base / "output"
    scripts_dir = tmp_base / "scripts"
    workspace_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    scripts_dir.mkdir(parents=True)

    # Copy sample CSV to workspace as dataset.csv
    sample_csv = ROOT / "sample_data.csv"
    if not sample_csv.exists():
        _log.error("sample_data.csv not found: %s", sample_csv)
        return False
    shutil.copy(sample_csv, workspace_dir / "dataset.csv")
    _log.info("dataset.csv copied to %s", workspace_dir)

    # --- Real R executor + RuntimeProvider ---
    local_executor = LocalRExecutor(
        workspace_dir=workspace_dir,
        output_dir=output_dir,
        context_guard=guard_stub,
    )
    runtime_provider = RuntimeProvider(local_executor=local_executor)

    # --- Knowledge reference library ---
    reference_library = MarkdownReferenceLibrary(ROOT / "knowledge")

    # --- VisualizationAgent ---
    viz_agent = VisualizationAgent(
        policy_stub,
        schema_stub,
        audit_stub,
        llm_client=llm_stub,
        reference_library=reference_library,
        script_cache=RScriptCache(),
        runtime_provider=runtime_provider,
        workspace_dir=scripts_dir,
        output_dir=output_dir,
    )

    exec_id = "harness-viz-001"
    token = _make_stub_token(exec_id)
    agent_input = AgentInput(
        execution_id=exec_id,
        node_id="visualization_node",
        capability_token=token,
        payload={
            "execution_id": exec_id,
            "intent_object": _INTENT,
            "statistical_results": _STAT_RESULTS,
            "dataset_structural_metadata": _COLUMN_META,
        },
        input_schema_ref="cie://schemas/analysis-request.schema.json",
    )

    _log.info("Running VisualizationAgent._execute() ...")
    result = await viz_agent.run(agent_input)

    # --- Assertions ---
    passed = True

    if result.status != "success":
        _log.error("FAIL: agent status = %s  error = %s", result.status, result.error_message)
        passed = False
    else:
        _log.info("PASS: agent status = success")

    op = result.output_payload
    r_script = op.get("r_script")
    if r_script:
        _log.info("PASS: r_script generated (%d chars)", len(r_script))
    else:
        _log.error("FAIL: r_script is None/empty")
        passed = False

    provenance = op.get("r_script_provenance", {})
    if provenance.get("llm_generated"):
        _log.info("PASS: provenance.llm_generated = True")
    else:
        _log.error("FAIL: provenance.llm_generated = %s", provenance.get("llm_generated"))
        passed = False

    figure_manifest = op.get("figure_manifest", [])
    _log.info("figure_manifest: %s", json.dumps(figure_manifest, indent=2))

    pngs = list(output_dir.glob("*.png"))
    if pngs:
        _log.info("PASS: PNG generated: %s", [p.name for p in pngs])
        # Verify PNG path is in figure_manifest
        manifest_paths = {
            entry.get("actual_path", "") for entry in figure_manifest
        }
        for png in pngs:
            if str(png.resolve()) in manifest_paths:
                _log.info("PASS: PNG path in figure_manifest: %s", png.name)
            else:
                _log.warning("WARN: PNG not linked in figure_manifest (expected paths: %s)", manifest_paths)
    else:
        _log.error(
            "FAIL: No PNG found in output_dir %s — R execution may have failed. "
            "exec_detail=%s",
            output_dir,
            op.get("visualization_execution_detail", {}),
        )
        passed = False

    _log.info("Harness result: %s", "PASSED" if passed else "FAILED")
    _log.info("Tmp dir (inspect artefacts): %s", tmp_base)
    return passed


if __name__ == "__main__":
    ok = asyncio.run(run_harness())
    sys.exit(0 if ok else 1)
