from __future__ import annotations

from pathlib import Path

import yaml

from cie.core.exceptions import WorkflowError


class SystemWorkflowRegistry:
    """Registry for administrative (system) workflows.

    Loaded from spec/system-workflow.yaml. Completely independent of
    WorkflowRegistry (spec/workflow.yaml), which serves Planner-dispatched
    analysis workflows.

    This class intentionally does NOT implement workflow_selection_rules or
    select_workflow() — those are Planner-only concepts (ADR-0001 / ADR-0003).
    Callers select system workflows by explicit workflow_id from a UI event,
    never by LLM-driven rule evaluation.
    """

    def __init__(self, spec_path: Path) -> None:
        raw = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
        if raw.get("registry_type") != "system":
            err = WorkflowError(
                f"Expected registry_type='system', got '{raw.get('registry_type')}'.",
            )
            err.error_code = "INVALID_SYSTEM_WORKFLOW_SPEC"
            raise err
        self._workflows: dict[str, dict] = {
            wf["workflow_id"]: wf for wf in raw.get("workflows", [])
        }

    def get_workflow(self, workflow_id: str) -> dict:
        """Return the workflow definition for *workflow_id*.

        Raises:
            WorkflowError: With ``error_code="SYSTEM_WORKFLOW_NOT_FOUND"`` if
                *workflow_id* is not registered.
        """
        try:
            return self._workflows[workflow_id]
        except KeyError:
            err = WorkflowError(
                f"System workflow '{workflow_id}' not found in SystemWorkflowRegistry.",
            )
            err.error_code = "SYSTEM_WORKFLOW_NOT_FOUND"
            raise err

    def list_workflow_ids(self) -> list[str]:
        """Return all registered system workflow IDs."""
        return list(self._workflows.keys())
