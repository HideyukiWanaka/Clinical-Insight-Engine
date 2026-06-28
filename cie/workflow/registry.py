"""CIE Platform — Workflow Registry.

Loads the four static workflow definitions from spec/workflow.yaml and
provides deterministic workflow selection via the WS-001 to WS-004 rules
(ADR-0001 §Workflow Selection Rules).

Key invariants (ADR-0001):
  - Workflow definitions are read-only after loading.
  - select_workflow() ignores any 'workflow_id' field already present in
    intent_object — the Orchestrator is the sole authority for that decision.
  - WS-001 is always evaluated before WS-002, WS-002 before WS-003, etc.
  - requires_human_clarification=true suspends selection immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from cie.core.exceptions import WorkflowError


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkflowNodeDef:
    """Immutable definition of a single DAG node.

    Attributes:
        node_id: Unique identifier within its workflow (e.g. ``"intake"``).
        node_type: Structural role of the node.
        agent_id: Agent responsible for executing this node.
        depends_on: Node IDs that must complete before this node may run.
        outputs: Artifact keys produced by this node.
        description: Optional human-readable description.
    """

    node_id: str
    node_type: Literal["task", "decision", "approval", "evaluation"]
    agent_id: str
    depends_on: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    description: str = ""


@dataclass(frozen=True)
class WorkflowDefinition:
    """Immutable, static definition of a workflow DAG.

    Attributes:
        workflow_id: Matches the key used in ``spec/workflow.yaml``.
        version: Semantic version string (e.g. ``"1.0"``).
        category: High-level grouping (e.g. ``"statistics"``).
        entrypoint: ``node_id`` of the first node to execute.
        nodes: Mapping from ``node_id`` to ``WorkflowNodeDef``.
    """

    workflow_id: str
    version: str
    category: str
    entrypoint: str
    nodes: dict[str, WorkflowNodeDef]

    def get_node(self, node_id: str) -> WorkflowNodeDef:
        """Return the node definition for ``node_id``.

        Raises:
            WorkflowError: If ``node_id`` is not defined in this workflow.
        """
        try:
            return self.nodes[node_id]
        except KeyError:
            raise WorkflowError(
                f"WORKFLOW_NODE_NOT_FOUND: node '{node_id}' does not exist "
                f"in workflow '{self.workflow_id}'.",
                workflow_id=self.workflow_id,
            ) from None

    def get_next_nodes(self, completed_node_id: str) -> list[WorkflowNodeDef]:
        """Return all nodes whose ``depends_on`` lists ``completed_node_id``.

        This is the standard DAG traversal query: given a node that just
        finished, which nodes are now unblocked?

        Args:
            completed_node_id: The ``node_id`` of the node that just completed.

        Returns:
            List of ``WorkflowNodeDef`` objects (may be empty).
        """
        return [
            node
            for node in self.nodes.values()
            if completed_node_id in node.depends_on
        ]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_VALID_NODE_TYPES: frozenset[str] = frozenset(
    {"task", "decision", "approval", "evaluation"}
)


class WorkflowRegistry:
    """In-memory store for all static workflow definitions.

    Load once at startup::

        registry = WorkflowRegistry.load_from_yaml(Path("spec/workflow.yaml"))
        definition = registry.get("clinical_analysis_standard")

    Workflow selection::

        workflow_id, rule_id, justification = registry.select_workflow(intent_obj)
    """

    def __init__(self) -> None:
        self._definitions: dict[str, WorkflowDefinition] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @classmethod
    def load_from_yaml(cls, workflow_yaml_path: Path) -> "WorkflowRegistry":
        """Parse ``spec/workflow.yaml`` and build a populated registry.

        Only the ``workflow_registry`` (for metadata) and ``workflows``
        (for DAG node definitions) sections are consumed.

        Args:
            workflow_yaml_path: Path to ``spec/workflow.yaml``.

        Returns:
            A fully populated :class:`WorkflowRegistry`.

        Raises:
            WorkflowError: If the YAML cannot be parsed or a required section
                is missing.
        """
        try:
            with workflow_yaml_path.open(encoding="utf-8") as fh:
                raw: dict = yaml.safe_load(fh)
        except Exception as exc:
            raise WorkflowError(
                f"WORKFLOW_YAML_LOAD_FAILED: cannot read {workflow_yaml_path}: {exc}"
            ) from exc

        # Build a lookup of version/category from workflow_registry entries
        meta_by_id: dict[str, dict] = {}
        for entry in raw.get("workflow_registry", []):
            wid = entry.get("id", "")
            meta_by_id[wid] = {
                "version": str(entry.get("version", "1.0")),
                "category": entry.get("category", ""),
            }

        workflows_raw: dict = raw.get("workflows", {})
        if not workflows_raw:
            raise WorkflowError(
                "WORKFLOW_YAML_MISSING_SECTION: 'workflows' section not found."
            )

        registry = cls()
        for wf_id, wf_body in workflows_raw.items():
            meta = meta_by_id.get(wf_id, {"version": "1.0", "category": ""})
            entrypoint: str = wf_body.get("start", "intake")
            nodes_raw: dict = wf_body.get("nodes", {})

            nodes: dict[str, WorkflowNodeDef] = {}
            for node_id, node_body in nodes_raw.items():
                raw_type = node_body.get("type", "task")
                node_type = raw_type if raw_type in _VALID_NODE_TYPES else "task"
                depends_raw = node_body.get("depends_on", [])
                depends_on: list[str] = (
                    depends_raw if isinstance(depends_raw, list) else [depends_raw]
                )
                outputs_raw = node_body.get("outputs", [])
                outputs: list[str] = (
                    outputs_raw if isinstance(outputs_raw, list) else [outputs_raw]
                )
                nodes[node_id] = WorkflowNodeDef(
                    node_id=node_id,
                    node_type=node_type,  # type: ignore[arg-type]
                    agent_id=node_body.get("agent", ""),
                    depends_on=depends_on,
                    outputs=outputs,
                    description=node_body.get("description", ""),
                )

            registry._definitions[wf_id] = WorkflowDefinition(
                workflow_id=wf_id,
                version=meta["version"],
                category=meta["category"],
                entrypoint=entrypoint,
                nodes=nodes,
            )

        return registry

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, workflow_id: str) -> WorkflowDefinition:
        """Return the definition for ``workflow_id``.

        Raises:
            WorkflowError: If ``workflow_id`` is not registered.
        """
        try:
            return self._definitions[workflow_id]
        except KeyError:
            raise WorkflowError(
                f"WORKFLOW_NOT_FOUND: '{workflow_id}' is not registered. "
                f"Available: {sorted(self._definitions)}",
                workflow_id=workflow_id,
            ) from None

    def list_workflow_ids(self) -> list[str]:
        """Return all registered workflow IDs in sorted order."""
        return sorted(self._definitions)

    # ------------------------------------------------------------------
    # Workflow selection (ADR-0001 §Workflow Selection Rules)
    # ------------------------------------------------------------------

    def select_workflow(
        self,
        intent_object: dict,
    ) -> tuple[str, str, str]:
        """Select a workflow ID using the deterministic WS-001..WS-004 rules.

        The ``workflow_id`` field in ``intent_object`` — if present — is
        **silently ignored**.  Only the Orchestrator may set workflow_id.

        Args:
            intent_object: The intent object produced by PlannerAgent.
                Must conform to ``analysis-request.schema.json``.

        Returns:
            A 3-tuple of ``(workflow_id, rule_id, justification)``.

        Raises:
            WorkflowError("WORKFLOW_SELECTION_SUSPENDED"): If
                ``intent_object.requires_human_clarification`` is ``True``.
        """
        # Guard: clarification not yet resolved
        if intent_object.get("requires_human_clarification", False):
            raise WorkflowError(
                "WORKFLOW_SELECTION_SUSPENDED: intent_object.requires_human_"
                "clarification=True. Workflow selection is deferred until the "
                "user has resolved the outstanding clarification."
            )

        outcome_type: str = intent_object.get("outcome_type", "") or ""
        objective: str = intent_object.get("objective", "") or ""

        # WS-001 — survival analysis (highest priority)
        if outcome_type == "survival":
            return (
                "clinical_analysis_survival",
                "WS-001",
                f"outcome_type={outcome_type!r} → clinical_analysis_survival (WS-001)",
            )

        # WS-002 — systematic review / meta-analysis
        if objective == "systematic_review":
            return (
                "clinical_analysis_meta",
                "WS-002",
                f"objective={objective!r} → clinical_analysis_meta (WS-002)",
            )

        # WS-003 — prediction model
        if objective == "prediction_model":
            return (
                "clinical_analysis_prediction",
                "WS-003",
                f"objective={objective!r} → clinical_analysis_prediction (WS-003)",
            )

        # WS-004 — default fallback
        return (
            "clinical_analysis_standard",
            "WS-004",
            f"no specific rule matched (objective={objective!r}, "
            f"outcome_type={outcome_type!r}) → clinical_analysis_standard (WS-004 default)",
        )
