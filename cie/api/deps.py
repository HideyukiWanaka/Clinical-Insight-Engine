"""CIE Platform — shared FastAPI handler helpers (Phase 1 / R1-2).

Centralises the capability-token lifecycle every handler shares, mirroring
``cie/ui/app.py:_execute_continuation`` (``cie/ui/app.py:593-651``):

    token = token_manager.issue(...)
    try:
        output = await agent.run(AgentInput(..., capability_token=token, ...))
    finally:
        token_manager.revoke(token)   # ADR: token always revoked

Keeping this in one place guarantees the try/finally revoke rule (CLAUDE.md)
holds for all endpoints and removes per-handler boilerplate.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from fastapi import Request

from cie.agents.base import AgentInput, AgentOutput
from cie.security.capability_token import CapabilityScope


def get_services(request: Request) -> dict:
    """Return the process-wide service container built at app startup."""
    return request.app.state.services


def get_dataset_context(request: Request) -> dict:
    """Return the server-side 'current dataset' context, or ``{}``.

    Set by ``POST /api/dataset`` (rest-api-contract §3.1 assumes the dataset is
    registered first). Single-user, 127.0.0.1-bound server, so one current
    dataset held on ``app.state`` is sufficient for Phase 1.
    """
    return getattr(request.app.state, "dataset_context", None) or {}


def new_execution_id() -> str:
    """Server-side uuid4 execution id (rest-api-contract §3)."""
    return str(uuid.uuid4())


async def invoke_agent(
    services: dict,
    *,
    agent_key: str,
    agent_id: str,
    step_id: str,
    scopes: Iterable[CapabilityScope],
    payload: dict,
    input_schema_ref: str,
    execution_id: str,
) -> AgentOutput:
    """Issue a token, run the agent, and always revoke (try/finally).

    Args:
        services: The shared service container.
        agent_key: Key of the agent instance in ``services``.
        agent_id: Canonical agent id used to scope the capability token.
        step_id: DAG step / node id this invocation is bound to.
        scopes: Capability scopes to request for the token.
        payload: The pre-assembled agent input payload.
        input_schema_ref: Schema URI validating ``payload`` inside the agent.
        execution_id: Server-minted execution id shared across the call.

    Returns:
        The :class:`AgentOutput` from ``agent.run`` (never raises for agent
        failures — those surface as ``status="failed"`` outputs).
    """
    token_manager = services["token_manager"]
    agent = services[agent_key]
    token = token_manager.issue(
        execution_id=execution_id,
        agent_id=agent_id,
        step_id=step_id,
        requested_scopes=set(scopes),
    )
    try:
        agent_input = AgentInput(
            execution_id=execution_id,
            node_id=step_id,
            capability_token=token,
            payload=payload,
            input_schema_ref=input_schema_ref,
        )
        return await agent.run(agent_input)
    finally:
        token_manager.revoke(token)
