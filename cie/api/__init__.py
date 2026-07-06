"""CIE Platform — API package (ADR-0005).

FastAPI layer that fronts the existing Agent runtime for the IDE-style
frontend (spec/api/rest-api-contract.md). Endpoints follow the same
directly-invoked pattern already used by continuation analysis
(``cie/ui/app.py`` ``_execute_continuation`` / ``_workbench_execute_code``):
issue a Capability Token, build an ``AgentInput``, call ``agent.run()``,
and revoke the token in a ``finally`` block. The Orchestrator DAG is not
involved.

No routes are implemented yet — this is Phase 0 scaffolding only.
Implementation begins in Phase 1.
"""
