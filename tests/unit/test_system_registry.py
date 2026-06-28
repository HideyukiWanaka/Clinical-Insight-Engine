from __future__ import annotations

from pathlib import Path

import pytest

from cie.core.exceptions import WorkflowError
from cie.workflow.registry import WorkflowRegistry
from cie.workflow.system_registry import SystemWorkflowRegistry

# Path to the real spec file so tests exercise the actual YAML
_SPEC_DIR = Path(__file__).parent.parent.parent / "spec"
_SYSTEM_SPEC = _SPEC_DIR / "system-workflow.yaml"
_ANALYSIS_SPEC = _SPEC_DIR / "workflow.yaml"


def _make_registry() -> SystemWorkflowRegistry:
    return SystemWorkflowRegistry(_SYSTEM_SPEC)


def test_get_knowledge_ingestion_workflow():
    reg = _make_registry()
    wf = reg.get_workflow("knowledge_ingestion")
    assert wf["workflow_id"] == "knowledge_ingestion"
    assert wf["trigger"] == "ui_event.document_upload"


def test_unknown_workflow_raises():
    reg = _make_registry()
    with pytest.raises(WorkflowError) as exc_info:
        reg.get_workflow("nonexistent_workflow")
    assert exc_info.value.error_code == "SYSTEM_WORKFLOW_NOT_FOUND"


def test_list_workflow_ids_returns_all():
    reg = _make_registry()
    ids = reg.list_workflow_ids()
    assert "knowledge_ingestion" in ids
    assert "skill_lifecycle" in ids


def test_system_registry_independent_of_analysis_registry():
    system_reg = _make_registry()
    analysis_reg = WorkflowRegistry.load_from_yaml(_ANALYSIS_SPEC)
    # Must be completely separate instances with no shared class hierarchy
    assert type(system_reg) is not type(analysis_reg)
    assert not isinstance(system_reg, WorkflowRegistry)
    assert not isinstance(analysis_reg, SystemWorkflowRegistry)


def test_planner_cannot_select_system_workflow():
    reg = _make_registry()
    # SystemWorkflowRegistry must NOT expose workflow_selection_rules or
    # select_workflow() — those are Planner-only concepts (ADR-0001 / ADR-0003)
    assert not hasattr(reg, "workflow_selection_rules"), (
        "SystemWorkflowRegistry must not have workflow_selection_rules"
    )
    assert not hasattr(reg, "select_workflow"), (
        "SystemWorkflowRegistry must not have select_workflow()"
    )
