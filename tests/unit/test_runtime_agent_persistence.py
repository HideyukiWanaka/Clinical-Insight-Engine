"""Unit tests for RuntimeAgent workspace-persistence wiring.

Focuses on the Phase 4 behaviour added to ``cie.agents.runtime.RuntimeAgent``:
- ``persist_workspace=True`` wraps the script (load/save.image) before writing
  it for execution (RT-002-safe upstream injection, spec §2).
- ``persist_workspace`` absent/False leaves the script untouched (backward
  compatible with the DAG path).
- ``workspace_summary.json`` under OUTPUT_DIR is flattened into a
  name→{class,summary} dict on the output payload (spec §2.1, §5).

The RuntimeProvider is mocked, so no real R is required here — the real-R E2E
path is covered by scratchpad/harness_workspace_persist.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cie.agents.base import AgentInput
from cie.agents.runtime import RuntimeAgent
from cie.runtime.r_executor import ExecutionResult
from cie.security.capability_token import CapabilityScope, CapabilityToken

EXEC_ID = str(uuid.uuid4())


@pytest.fixture
def token() -> CapabilityToken:
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id="runtime",
        bound_step_id="run",
        granted_scopes=frozenset(
            {CapabilityScope.RUNTIME_INVOKE_EXECUTION, CapabilityScope.AUDIT_WRITE_ENTRY}
        ),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )


def _exec_result() -> ExecutionResult:
    return ExecutionResult(
        execution_id=EXEC_ID,
        status="success",
        exit_code=0,
        duration_ms=10,
        stdout_digest="a" * 64,
        stderr_digest="b" * 64,
        sanitized_stdout_summary="ok",
        output_artifacts=[],
    )


def _make_agent(tmp_path: Path) -> tuple[RuntimeAgent, MagicMock, Path]:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    provider = MagicMock()
    provider.execute_r = AsyncMock(return_value=_exec_result())
    agent = RuntimeAgent(
        policy_engine=MagicMock(),
        schema_registry=MagicMock(),
        audit_service=MagicMock(),
        runtime_provider=provider,
        workspace_dir=tmp_path / "scripts",
        output_dir=output_dir,
    )
    return agent, provider, output_dir


def _input(payload: dict, token: CapabilityToken) -> AgentInput:
    return AgentInput(
        execution_id=EXEC_ID,
        node_id="run",
        capability_token=token,
        payload=payload,
        input_schema_ref="cie://schemas/task-context.schema.json",
    )


def _written_script(provider: MagicMock) -> str:
    script_path: Path = provider.execute_r.call_args.kwargs["script_path"]
    return script_path.read_text(encoding="utf-8")


async def test_persist_true_wraps_script(tmp_path: Path, token: CapabilityToken) -> None:
    agent, provider, _ = _make_agent(tmp_path)
    await agent._execute(_input({"r_script": "x <- 1", "persist_workspace": True}, token))
    written = _written_script(provider)
    assert "load(.cie_img)" in written
    assert "save.image(" in written
    assert "x <- 1" in written


async def test_persist_false_leaves_script_untouched(
    tmp_path: Path, token: CapabilityToken
) -> None:
    agent, provider, _ = _make_agent(tmp_path)
    await agent._execute(_input({"r_script": "x <- 1", "persist_workspace": False}, token))
    written = _written_script(provider)
    assert "save.image(" not in written
    assert written == "x <- 1"


async def test_persist_absent_defaults_to_no_wrapping(
    tmp_path: Path, token: CapabilityToken
) -> None:
    agent, provider, _ = _make_agent(tmp_path)
    await agent._execute(_input({"r_script": "x <- 1"}, token))
    assert "save.image(" not in _written_script(provider)


async def test_workspace_summary_flattened_onto_payload(
    tmp_path: Path, token: CapabilityToken
) -> None:
    agent, _, output_dir = _make_agent(tmp_path)
    # Simulate the array the R wrapper writes.
    (output_dir / "workspace_summary.json").write_text(
        json.dumps(
            [
                {"name": "data", "class": "data.frame", "summary": "5 obs of 2 vars"},
                {"name": "m", "class": "numeric", "summary": "num 3"},
            ]
        ),
        encoding="utf-8",
    )
    out = await agent._execute(_input({"r_script": "x <- 1", "persist_workspace": True}, token))
    summary = out.output_payload["workspace_summary"]
    assert summary["data"] == {"class": "data.frame", "summary": "5 obs of 2 vars"}
    assert summary["m"]["class"] == "numeric"


async def test_no_summary_key_when_file_absent(
    tmp_path: Path, token: CapabilityToken
) -> None:
    agent, _, _ = _make_agent(tmp_path)
    out = await agent._execute(_input({"r_script": "x <- 1", "persist_workspace": True}, token))
    assert "workspace_summary" not in out.output_payload


async def test_no_summary_key_when_persist_false(
    tmp_path: Path, token: CapabilityToken
) -> None:
    agent, _, output_dir = _make_agent(tmp_path)
    (output_dir / "workspace_summary.json").write_text("[]", encoding="utf-8")
    out = await agent._execute(_input({"r_script": "x <- 1", "persist_workspace": False}, token))
    assert "workspace_summary" not in out.output_payload
