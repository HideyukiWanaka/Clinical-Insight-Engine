"""Unit tests for cie.api.dialog — the Dialog agent's deterministic routing.

Two layers are covered:
- DialogRouter: a pure function over explicit + structural signals. Tool
  selection is deterministic and never inferred from free text (the safety
  invariant), so the routing table is exhaustively pinned here.
- DialogService: dispatches each route to a governed agent. Verified with fakes
  that the visualization/report tools run over the token lifecycle and emit the
  right terminal frame, and that missing prior results never fail silently (§5).
"""

from __future__ import annotations

import pytest

from cie.agents.base import AgentOutput
from cie.api.conversation import ConversationState
from cie.api.dialog import DialogRoute, DialogRouter, DialogService, DialogTurn

# ── DialogRouter: deterministic routing table ───────────────────────────────


class TestDialogRouterRoute:
    def test_bare_prompt_routes_to_plan(self) -> None:
        assert DialogRouter.route(DialogTurn(prompt="男女で比較")) is DialogRoute.PLAN

    def test_resolved_intent_routes_to_analysis(self) -> None:
        turn = DialogTurn(intent_object={"objective": "between_group_comparison"})
        assert DialogRouter.route(turn) is DialogRoute.ANALYSIS

    def test_empty_intent_object_is_not_an_intent(self) -> None:
        # An empty dict must fall through to PLAN, not ANALYSIS.
        assert DialogRouter.route(DialogTurn(intent_object={}, prompt="x")) is DialogRoute.PLAN

    def test_continuation_query_routes_to_continuation(self) -> None:
        turn = DialogTurn(
            intent_object={"objective": "x"}, continuation_query="効果量も出して"
        )
        assert DialogRouter.route(turn) is DialogRoute.CONTINUATION

    def test_explicit_visualization_tool_wins_over_continuation(self) -> None:
        # The explicit gate takes precedence over structural signals — a 図
        # affordance is never re-interpreted as a code refinement.
        turn = DialogTurn(
            intent_object={"objective": "x"},
            continuation_query="この結果で",
            requested_tool="visualization",
        )
        assert DialogRouter.route(turn) is DialogRoute.VISUALIZATION

    def test_explicit_reporting_tool_routes_to_report(self) -> None:
        turn = DialogTurn(intent_object={"objective": "x"}, requested_tool="reporting")
        assert DialogRouter.route(turn) is DialogRoute.REPORT

    @pytest.mark.parametrize(
        ("confidence", "clarify", "expected"),
        [
            (0.9, False, DialogRoute.ANALYSIS),
            (0.7, False, DialogRoute.ANALYSIS),  # boundary: >= 0.7 proceeds
            (0.69, False, DialogRoute.CONFIRM),
            (0.0, False, DialogRoute.CONFIRM),
            (0.95, True, DialogRoute.CLARIFY),  # clarification wins over confidence
        ],
    )
    def test_planner_output_gates(self, confidence, clarify, expected) -> None:
        assert DialogRouter.route_planner_output(confidence, clarify) is expected


# ── Fakes for DialogService dispatch ────────────────────────────────────────


class _FakeToken:
    token_id = "tok-1"


class _FakeTokenManager:
    def __init__(self) -> None:
        self.issued = 0
        self.revoked = 0

    def issue(self, **_kwargs) -> _FakeToken:
        self.issued += 1
        return _FakeToken()

    def revoke(self, _token) -> None:
        self.revoked += 1


class _FakeRunAgent:
    """Stub agent whose run() returns a canned AgentOutput (records the payload)."""

    def __init__(self, agent_id: str, payload: dict, status: str = "success") -> None:
        self.agent_id = agent_id
        self._payload = payload
        self._status = status
        self.last_payload: dict | None = None

    async def run(self, agent_input) -> AgentOutput:
        self.last_payload = agent_input.payload
        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status=self._status,
            output_payload=self._payload,
            output_schema_ref="cie://schemas/task-context.schema.json",
            error_message=None if self._status == "success" else "boom",
        )


def _make_services(**agents) -> dict:
    services = {"token_manager": _FakeTokenManager()}
    services.update(agents)
    return services


async def _collect(service: DialogService, turn: DialogTurn, state: ConversationState):
    return [frame async for frame in service.run_turn(turn, state)]


# ── DialogService: visualization / report tools ─────────────────────────────


@pytest.mark.asyncio
class TestDialogServiceTools:
    async def test_visualization_dispatch_emits_figures(self) -> None:
        viz = _FakeRunAgent(
            "visualization",
            {"figure_manifest": [{"figure_id": "fig_box_001", "actual_path": "/w/fig.png"}]},
        )
        services = _make_services(visualization=viz)
        service = DialogService(services, dataset_context={})
        state = ConversationState(conversation_id="c")

        turn = DialogTurn(
            intent_object={"objective": "between_group_comparison"},
            prior_statistical_results={"test": "welch_t", "p_value": 0.03},
            requested_tool="visualization",
        )
        frames = await _collect(service, turn, state)

        figures = next(f for f in frames if f["type"] == "figures")
        assert figures["figures"] == [{"title": "fig_box_001", "path": "/w/fig.png"}]
        # Ran over the governed agent with the prior results, token revoked.
        assert viz.last_payload["statistical_results"]["test"] == "welch_t"
        assert services["token_manager"].revoked == services["token_manager"].issued == 1
        # The assistant reply is recorded in the running history.
        assert state.turns[-1]["role"] == "assistant"
        assert "図" in state.turns[-1]["text"]

    async def test_report_dispatch_emits_manuscript(self) -> None:
        rep = _FakeRunAgent(
            "reporting",
            {"manuscript_sections": [
                {"section_id": "results", "content": "p=.03", "llm_generated": True},
            ]},
        )
        service = DialogService(_make_services(reporting=rep), dataset_context={})
        state = ConversationState(conversation_id="c")

        turn = DialogTurn(
            intent_object={"objective": "x"},
            prior_statistical_results={"p_value": 0.03},
            requested_tool="reporting",
        )
        frames = await _collect(service, turn, state)

        ms = next(f for f in frames if f["type"] == "manuscript")
        assert ms["manuscript_sections"] == [
            {"section_id": "results", "text": "p=.03", "is_ai_generated": True}
        ]

    async def test_visualization_without_prior_results_errors(self) -> None:
        # No statistics to visualise yet — never silent (§5), and no agent run.
        viz = _FakeRunAgent("visualization", {})
        service = DialogService(_make_services(visualization=viz), dataset_context={})
        state = ConversationState(conversation_id="c")

        turn = DialogTurn(intent_object={"objective": "x"}, requested_tool="visualization")
        frames = await _collect(service, turn, state)

        assert frames == [{"type": "error", "reason": "no_prior_results_for_visualization"}]
        assert viz.last_payload is None  # the agent was never invoked

    async def test_report_agent_failure_surfaces_reason(self) -> None:
        rep = _FakeRunAgent("reporting", {}, status="failed")
        service = DialogService(_make_services(reporting=rep), dataset_context={})
        state = ConversationState(conversation_id="c")

        turn = DialogTurn(
            intent_object={"objective": "x"},
            prior_statistical_results={"p_value": 0.03},
            requested_tool="reporting",
        )
        frames = await _collect(service, turn, state)
        err = next(f for f in frames if f["type"] == "error")
        assert err["reason"] == "boom"
