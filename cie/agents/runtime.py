"""CIE Platform — Runtime Agent: executes R scripts inside the sandbox.

Wraps :class:`~cie.runtime.runtime_provider.RuntimeProvider` so the Orchestrator
can dispatch the ``runtime_execution`` node like any other agent. Implements the
runtime portion of spec/workflow.yaml.

Integrity rule (RT-EXEC-001): this agent NEVER fabricates statistical results.
It executes only a genuine, upstream-provided R script. When no executable
script is present in the accumulated context, it returns a structured
``no_executable_script`` result instead of inventing output — a clinical tool
must never present computed numbers that were not actually produced by R.

Scope requirements (spec/permissions.yaml):
    - runtime.invoke_execution — launch the sandboxed R subprocess
    - audit.write_entry        — record execution in the audit log
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.audit import AuditService
from cie.core.exceptions import RuntimeExecutionError
from cie.runtime.runtime_provider import RuntimeProvider
from cie.runtime.workspace_wrapper import (
    WORKSPACE_SUMMARY_FILENAME,
    wrap_with_workspace_persistence,
)
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import CapabilityScope
from cie.security.policy_engine import PolicyEngine

_log = logging.getLogger(__name__)


class RuntimeAgent(BaseAgent):
    """Executes an upstream-generated R script via the RuntimeProvider.

    Args:
        policy_engine:    Enforces capability scope checks before execution.
        schema_registry:  Validates input and output payloads.
        audit_service:    Records execution outcomes.
        runtime_provider: Sandboxed R execution abstraction layer.
        workspace_dir:    Directory where the R script file is written before
                          execution.
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        schema_registry: SchemaRegistry,
        audit_service: AuditService,
        runtime_provider: RuntimeProvider,
        workspace_dir: Path | str,
        output_dir: Path | str | None = None,
    ) -> None:
        super().__init__(policy_engine, schema_registry, audit_service)
        self._runtime_provider = runtime_provider
        self._workspace_dir = Path(workspace_dir)
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        # Directory where the R script writes result.json (OUTPUT_DIR in the
        # sandbox). Used to parse machine-readable statistical results.
        self._output_dir = Path(output_dir) if output_dir is not None else None

    @property
    def agent_id(self) -> str:
        return "runtime"

    @property
    def input_schema_ref(self) -> str:
        return "cie://schemas/task-context.schema.json"

    @property
    def output_schema_ref(self) -> str:
        # Runtime execution results are internal artifacts chained forward via
        # accumulated_context; validated against the permissive dispatch schema.
        return "cie://schemas/task-context.schema.json"

    @property
    def required_scopes(self) -> list[CapabilityScope]:
        return [
            CapabilityScope.RUNTIME_INVOKE_EXECUTION,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ]

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        payload = agent_input.payload
        persist_workspace = bool(payload.get("persist_workspace", False))

        script_source = self._extract_script_source(payload)

        # RT-EXEC-001: never fabricate results. If upstream produced only a
        # specification (no runnable R code), report that honestly.
        if not script_source:
            _log.warning(
                "runtime_execution reached but no executable R script found in "
                "context; upstream produced a specification only."
            )
            output_payload = {
                "execution_id": agent_input.execution_id,
                "execution_result": {
                    "status": "no_executable_script",
                    "detail": (
                        "No executable R script was provided by upstream nodes. "
                        "The statistics stage emitted an r_script_specification "
                        "but not runnable R code, so nothing was executed. No "
                        "statistical results were computed."
                    ),
                },
                "generated_files": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            return AgentOutput(
                execution_id=agent_input.execution_id,
                agent_id=self.agent_id,
                status="success",
                output_payload=output_payload,
                output_schema_ref=self.output_schema_ref,
            )

        # Persist-workspace mode (ADR-0005 Principle 2): wrap the user script
        # with explicit load()/save.image()/summary code *upstream* of the
        # executor (RT-002: executor never edits scripts). The wrapped source is
        # what gets written, executed, and recorded in the audit log.
        script_to_run = (
            wrap_with_workspace_persistence(script_source)
            if persist_workspace
            else script_source
        )

        # Write the script to the workspace and execute it in the sandbox.
        script_path = self._workspace_dir / f"analysis_{uuid4().hex}.R"
        script_path.write_text(script_to_run, encoding="utf-8")

        try:
            result = await self._runtime_provider.execute_r(
                execution_id=agent_input.execution_id,
                script_path=script_path,
                capability_token=agent_input.capability_token,
            )
        except RuntimeExecutionError as exc:
            output_payload = {
                "execution_id": agent_input.execution_id,
                "execution_result": {
                    "status": "execution_failed",
                    "detail": str(exc),
                },
                "generated_files": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            return AgentOutput(
                execution_id=agent_input.execution_id,
                agent_id=self.agent_id,
                status="failed",
                output_payload=output_payload,
                output_schema_ref=self.output_schema_ref,
                error_code="RUNTIME_EXECUTION_FAILED",
                error_message=str(exc),
            )

        result_dict = asdict(result)
        # Parse the machine-readable result.json the R script wrote to OUTPUT_DIR
        # into statistical_results — the key every downstream agent
        # (visualization/reporting/reviewer) reads. Never fabricated: absent or
        # unparsable result.json yields statistical_results=None with a reason.
        statistical_results, stats_reason = self._parse_statistical_results()
        output_payload = {
            "execution_id": agent_input.execution_id,
            "execution_result": {
                "status": "completed" if result.exit_code == 0 else "nonzero_exit",
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "sanitized_stdout_summary": result.sanitized_stdout_summary,
                "r_version": result.r_version,
            },
            "statistical_results": statistical_results,
            "generated_files": list(result.output_artifacts),
            "runtime_execution_detail": result_dict,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if statistical_results is None:
            output_payload["statistical_results_reason"] = stats_reason
        # Surface the persisted R workspace variables (name → type/summary) so
        # the Workspace/Data pane can render them (spec §2.1, §5). Only present
        # when persistence is on and the script emitted the summary file.
        if persist_workspace:
            workspace_summary = self._read_workspace_summary()
            if workspace_summary is not None:
                output_payload["workspace_summary"] = workspace_summary
        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status="success",
            output_payload=output_payload,
            output_schema_ref=self.output_schema_ref,
        )

    def _parse_statistical_results(self) -> tuple[dict | None, str]:
        """Read and parse OUTPUT_DIR/result.json, if present.

        Returns (results, reason). ``results`` is None when the file is missing
        or unparsable (reason explains which). The parsed dict is passed through
        untouched — numbers are whatever the R script actually computed.
        """
        if self._output_dir is None:
            return None, "output_dir_not_configured"
        result_path = self._output_dir / "result.json"
        if not result_path.exists():
            return None, "result_json_not_produced_by_script"
        try:
            parsed = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"result_json_unparsable: {exc}"
        if not isinstance(parsed, dict):
            return None, "result_json_not_an_object"
        return parsed, ""

    def _read_workspace_summary(self) -> dict[str, dict] | None:
        """Read OUTPUT_DIR/workspace_summary.json into a name→descriptor map.

        The wrapper's R code (workspace_wrapper.py) writes a JSON *array* of
        ``{name, class, summary}`` objects (spec §2.1). This flattens it into a
        dict keyed by variable name so the API/frontend can render 名前・型・要約
        directly. Returns ``None`` when the file is missing or unparsable — the
        summary is a best-effort convenience, never fabricated.
        """
        if self._output_dir is None:
            return None
        summary_path = self._output_dir / WORKSPACE_SUMMARY_FILENAME
        if not summary_path.exists():
            return None
        try:
            parsed = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(parsed, list):
            return None
        summary: dict[str, dict] = {}
        for item in parsed:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                summary[item["name"]] = {
                    "class": item.get("class", ""),
                    "summary": item.get("summary", ""),
                }
        return summary

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_script_source(payload: dict) -> str | None:
        """Return an executable R script string from context, or None.

        Accepts several shapes that upstream nodes may use:
          - payload["r_script"]                          (str)
          - payload["r_script"]["source"]                (dict)
          - payload["generated_r_script"]                (str)
        A bare r_script_specification (function name/packages only) is NOT
        executable and yields None.
        """
        candidate = payload.get("r_script") or payload.get("generated_r_script")
        if isinstance(candidate, str) and candidate.strip():
            return candidate
        if isinstance(candidate, dict):
            source = candidate.get("source") or candidate.get("script")
            if isinstance(source, str) and source.strip():
                return source
        return None
