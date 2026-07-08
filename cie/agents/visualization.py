"""CIE Platform — Visualization Agent (Phase 2: LLM ggplot2 generation + execution).

Selects chart types, generates executable ggplot2 R scripts via the LLM (grounded
in the knowledge reference library), executes them in the sandbox, and writes real
PNG files.  Updates figure_manifest with actual output paths.

Key rules (agents/visualization.yaml):
  VZ-001  No raw patient data in the agent logic — only aggregated statistical results.
          (The generated R script reads dataset.csv inside the sandbox — acceptable.)
  VZ-002  Chart type selected from data characteristics, not aesthetics.
  VZ-003  All palettes colorblind-safe; Okabe-Ito is the default.
  VZ-004  Every figure must have a caption_draft.
  VZ-005  Schema-conforming JSON output only.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.audit import AuditService
from cie.core.exceptions import AgentError
from cie.cache.r_script_cache import RScriptCache
from cie.core.llm_client import LLMClient, LLMError
from cie.knowledge.reference_library import MarkdownReferenceLibrary
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import CapabilityScope
from cie.security.policy_engine import PolicyEngine
from cie.skills.loader import SkillLoader

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chart-key → Skill-ID mapping (ADR-0002: user/ > core/ priority via SkillLoader)
# ---------------------------------------------------------------------------

_CHART_TO_SKILL_ID: dict[str, str] = {
    "box_plot_with_jitter": "visualization/group-comparison",
    "violin_plot": "visualization/group-comparison",
    "slopegraph": "visualization/group-comparison",
    "scatter_plot_with_regression_line": "visualization/group-comparison",
    "kaplan_meier_curve": "visualization/survival",
    "grouped_bar_chart": "visualization/group-comparison",
    "histogram_with_density_overlay": "visualization/group-comparison",
    "forest_plot": "visualization/group-comparison",
}

# ---------------------------------------------------------------------------
# Colorblind-safe palette (VZ-003)
# ---------------------------------------------------------------------------

OKABE_ITO_PALETTE: list[str] = [
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#009E73",  # bluish green
    "#F0E442",  # yellow
    "#0072B2",  # blue
    "#D55E00",  # vermilion
    "#CC79A7",  # reddish purple
    "#000000",  # black
]

# ---------------------------------------------------------------------------
# Chart type catalogue (visualization.yaml chart_selection_framework)
# ---------------------------------------------------------------------------

_CHART_SPECS: dict[str, dict] = {
    "box_plot_with_jitter": {
        "chart_type": "box_plot_with_jitter",
        "ggplot2_geom": ["geom_boxplot", "geom_jitter"],
        "description": "Distribution comparison between groups with individual data points.",
    },
    "violin_plot": {
        "chart_type": "violin_plot",
        "ggplot2_geom": ["geom_violin", "geom_boxplot"],
        "description": "Kernel density mirrored for detailed distribution shape.",
    },
    "slopegraph": {
        "chart_type": "slopegraph",
        "ggplot2_geom": ["geom_line", "geom_point"],
        "description": "Paired data slope visualization showing individual trajectories.",
    },
    "scatter_plot_with_regression_line": {
        "chart_type": "scatter_plot_with_regression_line",
        "ggplot2_geom": ["geom_point", "geom_smooth"],
        "description": "Correlation scatter plot with fitted regression line and CI band.",
    },
    "kaplan_meier_curve": {
        "chart_type": "kaplan_meier_curve",
        "ggplot2_geom": ["geom_step", "geom_ribbon"],
        "description": "Survival probability over time with confidence bands.",
        "r_packages": ["survival", "survminer"],
    },
    "grouped_bar_chart": {
        "chart_type": "grouped_bar_chart",
        "ggplot2_geom": ["geom_col"],
        "description": "Proportional comparison of categorical outcomes between groups.",
    },
    "histogram_with_density_overlay": {
        "chart_type": "histogram_with_density_overlay",
        "ggplot2_geom": ["geom_histogram", "geom_density"],
        "description": "Distribution shape assessment for normality checking.",
    },
    "forest_plot": {
        "chart_type": "forest_plot",
        "ggplot2_geom": ["geom_pointrange"],
        "description": "Effect size summary with confidence intervals for multiple outcomes.",
    },
}

# ---------------------------------------------------------------------------
# ggplot2 R-script generation system prompt (knowledge-grounded LLM codegen)
# ---------------------------------------------------------------------------

_VZ_R_GEN_SYSTEM_PROMPT = """\
You are a ggplot2 visualization programmer for the CIE Platform. Produce a single,
complete, runnable R script that creates a publication-quality clinical figure.

STRICT REQUIREMENTS:
1. Output ONLY R code inside one ```r ... ``` fenced block. No prose outside it.
2. When raw data is needed for the chart (box plots, jitter, scatter, etc.), read:
       data <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"), "dataset.csv"),
                        stringsAsFactors = FALSE)
   Use the column names from dataset_columns. If group/outcome columns are ambiguous,
   select them defensively and comment your choice.
   For aggregated charts (forest plots, bar charts from summaries), build data frames
   directly from the statistical_results values provided.
3. Save the figure with ggsave EXACTLY as shown (use the figure_id from the request):
       ggsave(
         file.path(Sys.getenv("OUTPUT_DIR"), "figure_<figure_id>.png"),
         plot = p,
         width = 180, height = 120, units = "mm", dpi = 300
       )
4. set.seed(42) before any stochastic step.
5. Use the Okabe-Ito colorblind-safe palette (VZ-003):
       okabe_ito <- c("#E69F00","#56B4E9","#009E73","#F0E442",
                      "#0072B2","#D55E00","#CC79A7","#000000")
6. Base theme — apply exactly this to every figure:
       cie_theme <- theme_classic() +
         theme(
           text          = element_text(size = 10),
           axis.title    = element_text(size = 10, face = "bold"),
           axis.text     = element_text(size = 9),
           legend.title  = element_text(size = 9, face = "bold"),
           legend.text   = element_text(size = 9),
           plot.title    = element_text(size = 11, face = "bold"),
           panel.grid.major = element_line(color = "grey90", linewidth = 0.3),
           panel.grid.minor = element_blank()
         )
7. Ground your implementation in the provided KNOWLEDGE REFERENCE PATTERNS.
8. Add a statistical annotation (p-value and effect size) to the figure when provided.
9. Wrap the entire script in tryCatch so failures print a clear message and quit(status=1).
10. Never hard-code absolute paths; always use Sys.getenv("WORKSPACE_DIR") and
    Sys.getenv("OUTPUT_DIR") only.
11. Never call install.packages(), system(), system2(), shell(), or source().
"""


class VisualizationAgent(BaseAgent):
    """Scientific visualization agent: LLM-generated ggplot2 R + sandbox execution.

    Selects chart types from data characteristics (VZ-002), generates an executable
    ggplot2 R script via the LLM (grounded in the knowledge reference library), and
    optionally executes it to produce real PNG files with actual paths in figure_manifest.

    When llm_client/runtime_provider are None (unit-test mode) the agent falls back
    to a specification-only output (r_script=None, figure_manifest with expected paths)
    — all existing tests remain green.

    Args:
        policy_engine: Enforces capability scope checks.
        schema_registry: Validates input and output payloads.
        audit_service: Records execution outcomes.
        llm_client: LLM used for ggplot2 R-script generation. None → spec-only.
        reference_library: Markdown RAG source (ggplot2_best_practices, chart_selection).
        script_cache: Token-saving cache for structurally-identical scripts.
        runtime_provider: Sandbox R executor. None → skip inline execution.
        workspace_dir: Directory where R scripts are written before execution.
        output_dir: Directory where the sandbox writes PNG output files.
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        schema_registry: SchemaRegistry,
        audit_service: AuditService,
        llm_client: LLMClient | None = None,
        reference_library: MarkdownReferenceLibrary | None = None,
        script_cache: RScriptCache | None = None,
        runtime_provider=None,
        workspace_dir: Path | str | None = None,
        output_dir: Path | str | None = None,
        skill_loader: SkillLoader | None = None,
    ) -> None:
        super().__init__(policy_engine, schema_registry, audit_service)
        self._llm_client = llm_client
        self._reference_library = reference_library
        self._script_cache = script_cache
        self._runtime_provider = runtime_provider
        self._workspace_dir = Path(workspace_dir) if workspace_dir is not None else None
        self._output_dir = Path(output_dir) if output_dir is not None else None
        self._skill_loader = skill_loader
        if self._workspace_dir is not None:
            self._workspace_dir.mkdir(parents=True, exist_ok=True)

    @property
    def agent_id(self) -> str:
        return "visualization"

    @property
    def input_schema_ref(self) -> str:
        return "cie://schemas/analysis-request.schema.json"

    @property
    def output_schema_ref(self) -> str:
        return "cie://schemas/visualization-plan.schema.json"

    @property
    def required_scopes(self) -> list[CapabilityScope]:
        scopes = [
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.R_CODE_GENERATE_TEMPLATE,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ]
        if self._runtime_provider is not None:
            scopes.append(CapabilityScope.RUNTIME_INVOKE_EXECUTION)
        return scopes

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        """Select chart type, generate ggplot2 R, execute sandbox, return figure_manifest.

        Steps:
          1. VZ-001: Verify statistical_results present.
          2. Extract intent_object and statistical_results.
          3. Select chart type (VZ-002).
          4. Build figure specification with caption_draft (VZ-004).
          5. Generate executable ggplot2 R script via LLM + knowledge RAG.
          6. If runtime_provider configured: execute R, collect real PNG paths.
          7. Return AgentOutput.
        """
        payload = agent_input.payload

        # Step 1 — VZ-001: statistical_results must be present
        statistical_results = payload.get("statistical_results")
        if not statistical_results:
            raise AgentError(
                "MISSING_STATISTICAL_INPUT: Visualization requires validated "
                "statistical results from the Statistics Agent.",
                agent_id=self.agent_id,
            )

        # Step 2 — extract context
        intent_obj: dict = payload.get("intent_object") or {}
        objective: str = intent_obj.get("objective", "")
        outcome_type: str = intent_obj.get("outcome_type", "unknown")
        paired: bool | None = intent_obj.get("paired")
        journal_guidelines: dict = payload.get("journal_figure_guidelines") or {}
        column_metadata: dict = (
            payload.get("dataset_structural_metadata")
            or payload.get("variable_metadata")
            or {}
        )
        # Continuation mode: prior_statistical_results annotate the caption
        prior_statistical_results: dict | None = payload.get("prior_statistical_results")
        is_continuation: bool = bool(payload.get("continuation_query"))

        # Step 3 — chart type selection (VZ-002)
        chart_key = self._select_chart_type(objective, outcome_type, paired)
        chart_base = _CHART_SPECS.get(chart_key, _CHART_SPECS["box_plot_with_jitter"])

        # Step 4 — build figure specification (VZ-004: caption required)
        now_iso = datetime.now(timezone.utc).isoformat()
        figure_id = f"fig_{chart_base['chart_type']}_001"
        figure_spec = {
            "figure_id": figure_id,
            "chart_type": chart_base["chart_type"],
            "ggplot2_geoms": chart_base["ggplot2_geom"],
            "description": chart_base["description"],
            "color_palette": OKABE_ITO_PALETTE,  # VZ-003
            "palette_name": "Okabe-Ito",
            "output_standards": {
                "resolution_dpi": journal_guidelines.get("resolution_dpi", 300),
                "format": "png",
                "font_family": journal_guidelines.get("font_family", "Helvetica Neue"),
                "base_font_size_pt": 10,
                "figure_width_mm": 180,
                "figure_height_mm": 120,
            },
            "caption_draft": {
                "figure_label": "Figure 1",
                "description": chart_base["description"],
                "statistical_annotations": [
                    "p-value",
                    "effect size",
                    "95% confidence interval",
                    "n per group",
                ],
                "note": "Values are mean ± SD unless otherwise stated.",
                "is_continuation": is_continuation,
                "prior_method_id": (
                    prior_statistical_results.get("method_id")
                    if prior_statistical_results else None
                ),
            },
        }

        # R-script packages (preserved for r_script_specification backward compat)
        r_packages = list(chart_base.get("r_packages", ["ggplot2"]))
        if "ggplot2" not in r_packages:
            r_packages.insert(0, "ggplot2")

        # Step 5 — generate executable R script via LLM + RAG
        r_script, provenance = await self._generate_visualization_r_script(
            chart_key=chart_key,
            figure_id=figure_id,
            chart_base=chart_base,
            intent_obj=intent_obj,
            statistical_results=statistical_results,
            column_metadata=column_metadata,
        )

        # Step 6 — execute R in sandbox if runtime_provider is configured
        figure_manifest = [
            {
                "figure_id": figure_id,
                "expected_filename": f"{figure_id}.png",
                "format": "png",
                "resolution_dpi": 300,
            }
        ]
        execution_detail: dict = {}

        if r_script and self._runtime_provider is not None and self._workspace_dir is not None:
            script_path = self._workspace_dir / f"viz_{uuid4().hex}.R"
            script_path.write_text(r_script, encoding="utf-8")
            try:
                from cie.core.exceptions import RuntimeExecutionError
                result = await self._runtime_provider.execute_r(
                    execution_id=agent_input.execution_id,
                    script_path=script_path,
                    capability_token=agent_input.capability_token,
                )
                execution_detail = {
                    "status": "completed" if result.exit_code == 0 else "nonzero_exit",
                    "exit_code": result.exit_code,
                    "duration_ms": result.duration_ms,
                }
                # Update figure_manifest with real PNG paths from OUTPUT_DIR
                real_paths = self._collect_figure_paths(figure_id)
                if real_paths:
                    figure_manifest = real_paths
                    provenance["png_generated"] = True
                else:
                    provenance["png_generated"] = False
                    provenance["png_reason"] = "no_output_png_found"
            except Exception as exc:  # noqa: BLE001
                _log.warning("Visualization R execution failed: %s", exc)
                execution_detail = {"status": "execution_failed", "detail": str(exc)}
                provenance["png_generated"] = False
                provenance["png_reason"] = str(exc)

        # Step 7 — assemble output payload
        output_payload: dict = {
            "execution_id": agent_input.execution_id,
            "visualization_specifications": [figure_spec],
            "r_script_specification": {
                "primary_function": "ggplot",
                "packages_required": r_packages,
                "theme": "theme_classic",
                "seed": 42,
            },
            "r_script": r_script,
            "r_script_provenance": provenance,
            "figure_manifest": figure_manifest,
            "caption_drafts": [figure_spec["caption_draft"]],
            "created_at": now_iso,
        }
        if execution_detail:
            output_payload["visualization_execution_detail"] = execution_detail

        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status="success",
            output_payload=output_payload,
            output_schema_ref=self.output_schema_ref,
        )

    # ------------------------------------------------------------------
    # LLM ggplot2 R-script generation (knowledge-grounded, cached)
    # ------------------------------------------------------------------

    async def _generate_visualization_r_script(
        self,
        chart_key: str,
        figure_id: str,
        chart_base: dict,
        intent_obj: dict,
        statistical_results: dict,
        column_metadata: dict,
    ) -> tuple[str | None, dict]:
        """Generate a ggplot2 R script for the selected chart via the LLM.

        Follows the exact same pattern as StatisticsAgent._generate_r_script:
        cache lookup → RAG retrieval → LLM call → cache store.

        Returns:
            (r_script, provenance). r_script is None when no LLM is configured.
        """
        provenance: dict = {
            "llm_generated": False,
            "from_cache": False,
            "knowledge_references": [],
            "chart_type": chart_key,
            "figure_id": figure_id,
        }

        if self._llm_client is None:
            provenance["reason"] = "no_llm_client_configured"
            return None, provenance

        column_signature = json.dumps(column_metadata, sort_keys=True, ensure_ascii=False)

        # 1. Cache lookup
        signature = ""
        if self._script_cache is not None:
            signature = RScriptCache.make_signature(
                chart_key, intent_obj, column_signature
            )
            cached = self._script_cache.get(
                signature,
                provider=self._llm_client.provider,
                model=self._llm_client.model,
            )
            if cached is not None:
                provenance["llm_generated"] = True
                provenance["from_cache"] = True
                return cached, provenance

        # 2. RAG retrieval from knowledge/official/visualization/
        references: list = []
        if self._reference_library is not None:
            query_terms = [
                chart_key,
                chart_base["chart_type"],
                intent_obj.get("objective", ""),
                intent_obj.get("outcome_type", ""),
                "ggplot2",
            ]
            references = self._reference_library.retrieve(query_terms, top_k=4)
            provenance["knowledge_references"] = [r.title for r in references]

        # 3. Build prompt (optionally grounded with SKILL.md instructions)
        skill_id = _CHART_TO_SKILL_ID.get(chart_key)
        skill_block = (
            self._skill_loader.get_skill_prompt_block(skill_id)
            if self._skill_loader is not None and skill_id
            else ""
        )
        system_prompt_with_skill = _VZ_R_GEN_SYSTEM_PROMPT + skill_block
        user_message = self._build_viz_r_gen_user_message(
            chart_key=chart_key,
            figure_id=figure_id,
            chart_base=chart_base,
            intent_obj=intent_obj,
            statistical_results=statistical_results,
            column_metadata=column_metadata,
            references=references,
        )
        try:
            raw = await self._llm_client.complete(system_prompt_with_skill, user_message)
        except LLMError as exc:
            _log.warning("Visualization R-script LLM generation failed: %s", exc)
            provenance["reason"] = f"llm_error: {exc}"
            return None, provenance

        r_script = self._extract_r_code(raw)
        if not r_script:
            provenance["reason"] = "empty_or_unparsable_llm_response"
            return None, provenance

        provenance["llm_generated"] = True

        # 4. Cache for reuse
        if self._script_cache is not None and signature:
            self._script_cache.put(
                signature,
                r_script,
                provider=self._llm_client.provider,
                model=self._llm_client.model,
                method_id=chart_key,
            )

        return r_script, provenance

    @staticmethod
    def _build_viz_r_gen_user_message(
        chart_key: str,
        figure_id: str,
        chart_base: dict,
        intent_obj: dict,
        statistical_results: dict,
        column_metadata: dict,
        references: list,
    ) -> str:
        """Assemble the user turn for ggplot2 R-script generation."""
        reference_block = "\n\n".join(
            f"### Reference: {r.title}\n{r.excerpt()}" for r in references
        ) or "(no matching reference documents found)"

        # Truncate statistical_results for prompt safety
        safe_stats = {
            k: v for k, v in statistical_results.items()
            if k in {
                "method_id", "test_name", "test_statistic", "p_value",
                "effect_size", "effect_size_measure", "ci_lower", "ci_upper",
                "sample_size", "group_summaries",
            }
        }

        request = {
            "chart_type": chart_key,
            "figure_id": figure_id,
            "chart_description": chart_base["description"],
            "ggplot2_geoms": chart_base["ggplot2_geom"],
            "intent_object": {
                "objective": intent_obj.get("objective"),
                "outcome_type": intent_obj.get("outcome_type"),
                "paired": intent_obj.get("paired"),
                "outcome_variables": intent_obj.get("outcome_variables", []),
                "predictor_variables": intent_obj.get("predictor_variables", []),
            },
            "statistical_results": safe_stats,
            "dataset_columns": column_metadata,
        }
        return (
            "Generate a complete, runnable ggplot2 R script for the figure below.\n\n"
            "=== VISUALIZATION REQUEST ===\n"
            f"{json.dumps(request, ensure_ascii=False, indent=2)}\n\n"
            "=== KNOWLEDGE REFERENCE PATTERNS (ground your script in these) ===\n"
            f"{reference_block}\n"
        )

    @staticmethod
    def _extract_r_code(raw_text: str) -> str | None:
        """Extract R source from an LLM response (same as StatisticsAgent)."""
        match = re.search(r"```(?:r|R)?\s*\n(.*?)```", raw_text, re.DOTALL)
        if match:
            code = match.group(1).strip()
            return code or None
        text = raw_text.strip()
        return text or None

    def _collect_figure_paths(self, figure_id: str) -> list[dict]:
        """Scan OUTPUT_DIR for PNG files matching the figure_id.

        Returns a list of figure_manifest entries with real absolute paths.
        Returns an empty list if output_dir is not configured or no PNGs found.
        """
        if self._output_dir is None or not self._output_dir.exists():
            return []
        pattern = f"*{figure_id}*.png"
        # Also match any PNG (in case figure_id not in filename but PNG was generated)
        pngs = sorted(self._output_dir.glob(pattern))
        if not pngs:
            pngs = sorted(self._output_dir.glob("*.png"))
        return [
            {
                "figure_id": figure_id,
                "actual_path": str(p.resolve()),
                "filename": p.name,
                "format": "png",
                "resolution_dpi": 300,
            }
            for p in pngs
        ]

    def _select_chart_type(
        self,
        objective: str,
        outcome_type: str,
        paired: bool | None,
    ) -> str:
        """Map study objective to a chart type key (VZ-002).

        Selection is driven by data characteristics, not aesthetics.
        """
        if objective == "survival_analysis" or outcome_type == "survival":
            return "kaplan_meier_curve"

        if objective in {"correlation_analysis", "regression_analysis"}:
            return "scatter_plot_with_regression_line"

        if outcome_type in {
            "categorical_binary", "categorical_nominal", "categorical_ordinal"
        }:
            return "grouped_bar_chart"

        if objective in {"descriptive_only"}:
            return "histogram_with_density_overlay"

        # Continuous group comparison
        if paired:
            return "slopegraph"

        return "box_plot_with_jitter"
