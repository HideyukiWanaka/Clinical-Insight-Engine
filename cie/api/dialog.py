"""Dialog agent — deterministic turn orchestration for WS /ws/chat (Phase 2).

This is the conversational core's brain, extracted from the WS route handler
into one governed, testable unit. It takes a parsed chat turn plus the running
:class:`ConversationState` and yields the stream of frames the socket sends,
choosing *what to do* by explicit, deterministic gates — never by letting an
LLM decide.

Deterministic-gated tool routing (safety, CLAUDE.md / ADR-0001 / ADR-0005):
  1. An explicit ``requested_tool`` from a UI affordance (「この結果で図」「原稿に
     する」) is the highest-priority gate — the user picked the tool, so there is
     no inference to get wrong.
  2. Otherwise the route follows *structural* signals: a follow-up
     (``continuation_query``) refines the prior analysis; a resolved
     ``intent_object`` streams a proposal; a bare ``prompt`` runs the Planner.
  3. The Planner's own ``confidence``/``requires_clarification`` signals gate the
     clarify / confirm / proceed decision (unchanged from Phase 2.2).

Crucially, tool selection is NOT inferred from free text: "図のタイトルを変えて"
is a code refinement (continuation), not a request to run the figure tool, and
guessing from keywords would misroute it. Every branch dispatches to an existing
governed agent (issue token → schema-validated AgentInput → agent enforces
scope/schema/audit → revoke); this service only chooses between them. R
execution stays human-gated (POST /api/run).

Frames yielded (each a JSON object with ``type``): intent, clarify, confirm,
delta, proposal, figures, manuscript, error. Never silent (§5): anything that
cannot complete yields an ``error`` frame carrying a reason.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum

from cie.agents.base import AgentInput
from cie.api.conversation import ConversationState
from cie.api.deps import invoke_agent, new_execution_id
from cie.api.intent_display import resolve_intent_display
from cie.security.capability_token import CapabilityScope

_log = logging.getLogger(__name__)

# Confidence at/above which an unambiguous intent skips the confirm gate and
# streams the proposal directly (matches ChatPane's HIGH_CONFIDENCE / CA-002).
_HIGH_CONFIDENCE = 0.7

# Permissive dispatch schema the conversational Statistics/Visualization/
# Reporting payloads validate against (the strict analysis-request schema is the
# Planner *output* shape, not this *input* shape — see routes/propose.py).
_TASK_CONTEXT_SCHEMA_REF = "cie://schemas/task-context.schema.json"
_PLANNER_INPUT_SCHEMA_REF = "cie://schemas/planner-input.schema.json"

# Tools a UI affordance may request explicitly (the deterministic gate). Kept a
# closed set so an unknown value can never dispatch somewhere unexpected.
_VALID_TOOLS = frozenset({"visualization", "reporting"})


class DialogRoute(str, Enum):
    """The closed set of actions a chat turn can deterministically resolve to."""

    PLAN = "plan"  # bare prompt → run the Planner first, then re-route
    CLARIFY = "clarify"  # Planner needs a choice
    CONFIRM = "confirm"  # low-confidence intent awaiting the user's OK
    ANALYSIS = "analysis"  # stream a proposal for a resolved intent
    CONTINUATION = "continuation"  # stream a follow-up refining the prior analysis
    VISUALIZATION = "visualization"  # figures from the prior results
    REPORT = "report"  # manuscript from the prior results


@dataclass
class DialogTurn:
    """A parsed chat turn — the router's input (all fields already validated)."""

    prompt: str = ""
    intent_object: dict | None = None
    continuation_query: str = ""
    prior_statistical_results: dict | None = None
    prior_r_script: str | None = None
    requested_tool: str = ""

    @property
    def has_intent(self) -> bool:
        """True when a resolved (non-empty) intent_object rides with the turn."""
        return isinstance(self.intent_object, dict) and bool(self.intent_object)

    @property
    def is_continuation(self) -> bool:
        """True when the turn is a follow-up refining the prior analysis."""
        return bool(self.continuation_query)

    @property
    def user_text(self) -> str:
        """The user-visible text of this turn (follow-up query, else prompt)."""
        return self.continuation_query or self.prompt


class DialogRouter:
    """Pure, deterministic routing — no LLM, no I/O. Trivially testable."""

    @staticmethod
    def route(turn: DialogTurn) -> DialogRoute:
        """Resolve a turn to its route by explicit + structural signals only."""
        # 1. Explicit tool request (the deterministic gate) wins outright.
        if turn.requested_tool == "visualization":
            return DialogRoute.VISUALIZATION
        if turn.requested_tool == "reporting":
            return DialogRoute.REPORT
        # 2. Structural signals.
        if turn.is_continuation:
            return DialogRoute.CONTINUATION
        if turn.has_intent:
            return DialogRoute.ANALYSIS
        return DialogRoute.PLAN

    @staticmethod
    def route_planner_output(
        confidence: float, requires_clarification: bool
    ) -> DialogRoute:
        """Gate the Planner's output into clarify / confirm / proceed."""
        if requires_clarification:
            return DialogRoute.CLARIFY
        if confidence < _HIGH_CONFIDENCE:
            return DialogRoute.CONFIRM
        return DialogRoute.ANALYSIS


class DialogService:
    """Orchestrates one chat turn end-to-end over the governed agents.

    Holds no per-turn state itself; the running history lives in the
    :class:`ConversationState` passed to :meth:`run_turn`. Constructed per
    connection so it can carry the request's dataset context.
    """

    def __init__(self, services: dict, dataset_context: dict) -> None:
        """Bind the shared service container and the current dataset context."""
        self._services = services
        self._dataset_context = dataset_context or {}
        self._router = DialogRouter()

    async def run_turn(
        self, turn: DialogTurn, state: ConversationState
    ) -> AsyncIterator[dict]:
        """Route a turn and yield the frames the socket should send."""
        route = self._router.route(turn)
        if route is DialogRoute.PLAN:
            async for frame in self._plan_and_route(turn, state):
                yield frame
        elif route in (DialogRoute.ANALYSIS, DialogRoute.CONTINUATION):
            if turn.user_text:
                state.add_turn("user", turn.user_text)
            async for frame in self._stream_proposal(
                turn.intent_object or {}, turn, state
            ):
                yield frame
        elif route is DialogRoute.VISUALIZATION:
            async for frame in self._dispatch_visualization(turn, state):
                yield frame
        elif route is DialogRoute.REPORT:
            async for frame in self._dispatch_report(turn, state):
                yield frame

    # ------------------------------------------------------------------
    # PLAN → clarify / confirm / analysis
    # ------------------------------------------------------------------

    async def _plan_and_route(
        self, turn: DialogTurn, state: ConversationState
    ) -> AsyncIterator[dict]:
        """Run the Planner, then emit the routing frame (clarify/confirm/intent)."""
        # History EXCLUDES the current prompt (it rides separately, matching
        # /api/intent), so read it before recording this turn.
        history = state.history()
        col_meta = self._dataset_context.get("dataset_structural_metadata", {})
        alias_map = self._dataset_context.get("var_n_alias_map", {})
        masked_vars = set(self._dataset_context.get("pii_masked_vars", []))

        output = await invoke_agent(
            self._services,
            agent_key="planner",
            agent_id="planner",
            step_id="ws_chat_intent",
            scopes=[
                CapabilityScope.DATASET_PROXY_METADATA,
                CapabilityScope.WORKFLOW_STATE_READ,
                CapabilityScope.AUDIT_WRITE_ENTRY,
            ],
            payload={
                "user_natural_language_prompt": turn.prompt,
                "dataset_structural_metadata": col_meta,
                "conversation_history": history,
                "inject_raw_data_rows": False,
            },
            input_schema_ref=_PLANNER_INPUT_SCHEMA_REF,
            execution_id=new_execution_id(),
        )

        # Record the turn now that the Planner has read the prior history.
        state.add_turn("user", turn.prompt)

        if output.status not in ("success", "clarification_required"):
            yield {"type": "error", "reason": output.error_message or "planner_failed"}
            return

        op = output.output_payload
        intent_object = op.get("intent_object", {}) or {}
        clarification_options = op.get("clarification_options") or []
        confidence = float(op.get("confidence_score") or 0.0)
        requires_clarification = bool(op.get("requires_human_clarification", False))

        # Un-mask var_n aliases in user-facing prose so the chat never shows raw
        # internal identifiers like "var_4" (Fix C) — same helper as /api/intent.
        resolve_intent_display(
            intent_object, clarification_options, alias_map, masked_vars
        )
        summary = intent_object.get("natural_language_summary") or ""

        planner_route = self._router.route_planner_output(
            confidence, requires_clarification
        )
        if planner_route is DialogRoute.CLARIFY:
            state.add_turn("assistant", summary or "確認のため選択肢を提示しました。")
            yield {
                "type": "clarify",
                "intent_object": intent_object,
                "clarification_options": clarification_options,
            }
            return
        if planner_route is DialogRoute.CONFIRM:
            state.add_turn("assistant", summary or "意図を確認しました。")
            yield {"type": "confirm", "intent_object": intent_object}
            return

        # High confidence & unambiguous — echo the understood intent (transparency,
        # never a silent hand-off) and proceed to stream the proposal.
        yield {
            "type": "intent",
            "intent_object": intent_object,
            "confidence_score": confidence,
        }
        async for frame in self._stream_proposal(
            intent_object, DialogTurn(intent_object=intent_object), state
        ):
            yield frame

    # ------------------------------------------------------------------
    # ANALYSIS / CONTINUATION → streamed proposal
    # ------------------------------------------------------------------

    async def _stream_proposal(
        self, intent_object: dict, turn: DialogTurn, state: ConversationState
    ) -> AsyncIterator[dict]:
        """Stream a conversational proposal over the governed Statistics agent.

        Token issued here, always revoked in finally (same lifecycle as
        cie/api/deps.invoke_agent). A continuation turn adds its query + prior
        results/script so the proposal extends the prior analysis.
        """
        payload: dict = {
            "data_quality_report": {"quality_gate_passed": True},
            "intent_object": intent_object,
            "dataset_structural_metadata": self._dataset_context.get(
                "dataset_structural_metadata", {}
            ),
            "var_n_alias_map": self._dataset_context.get("var_n_alias_map", {}),
            "conversation_history": state.history(),
            "conversational_mode": True,
            "inject_raw_data_rows": False,
        }
        if turn.is_continuation:
            payload["continuation_query"] = turn.continuation_query
            payload["prior_statistical_results"] = turn.prior_statistical_results
            payload["prior_r_script"] = turn.prior_r_script

        execution_id = new_execution_id()
        token_manager = self._services["token_manager"]
        agent = self._services["statistics"]
        token = token_manager.issue(
            execution_id=execution_id,
            agent_id="statistics",
            step_id="ws_chat",
            requested_scopes={
                CapabilityScope.DATASET_READ_VALIDATED,
                CapabilityScope.R_CODE_GENERATE_TEMPLATE,
                CapabilityScope.AUDIT_WRITE_ENTRY,
            },
        )
        agent_input = AgentInput(
            execution_id=execution_id,
            node_id="ws_chat",
            capability_token=token,
            payload=payload,
            input_schema_ref=_TASK_CONTEXT_SCHEMA_REF,
        )
        try:
            async for event in agent.stream_conversational_proposal(agent_input):
                if event.get("type") == "proposal":
                    proposal = event.get("analysis_proposal") or {}
                    state.add_turn(
                        "assistant", proposal.get("explanation_markdown", "")
                    )
                    yield {
                        "type": "proposal",
                        "execution_id": execution_id,
                        "analysis_proposal": proposal,
                        "r_script_provenance": event.get("r_script_provenance") or {},
                    }
                else:
                    yield event
        finally:
            # ADR: the capability token is always revoked (try/finally).
            token_manager.revoke(token)

    # ------------------------------------------------------------------
    # VISUALIZATION / REPORT → governed one-shot dispatch on the prior results
    # ------------------------------------------------------------------

    async def _dispatch_visualization(
        self, turn: DialogTurn, state: ConversationState
    ) -> AsyncIterator[dict]:
        """Generate figures from the prior results via the Visualization agent."""
        if turn.user_text:
            state.add_turn("user", turn.user_text)
        stats = turn.prior_statistical_results
        if not stats:
            # Nothing to visualise yet — never silent (§5).
            yield {"type": "error", "reason": "no_prior_results_for_visualization"}
            return

        execution_id = new_execution_id()
        output = await invoke_agent(
            self._services,
            agent_key="visualization",
            agent_id="visualization",
            step_id="ws_chat_visualize",
            scopes=[
                CapabilityScope.DATASET_READ_VALIDATED,
                CapabilityScope.R_CODE_GENERATE_TEMPLATE,
                CapabilityScope.RUNTIME_INVOKE_EXECUTION,
                CapabilityScope.AUDIT_WRITE_ENTRY,
            ],
            payload={
                "statistical_results": stats,
                "intent_object": turn.intent_object or {},
                "dataset_structural_metadata": self._dataset_context.get(
                    "dataset_structural_metadata", {}
                ),
                "var_n_alias_map": self._dataset_context.get("var_n_alias_map", {}),
                "inject_raw_data_rows": False,
            },
            input_schema_ref=_TASK_CONTEXT_SCHEMA_REF,
            execution_id=execution_id,
        )
        if output.status != "success":
            yield {"type": "error", "reason": output.error_message or "visualization_failed"}
            return

        manifest = output.output_payload.get("figure_manifest") or []
        figures = [
            {"title": f.get("figure_id", "Figure"), "path": f.get("actual_path")}
            for f in manifest
            if isinstance(f, dict)
        ]
        # png_generated is False/"partial" when the script produced fewer PNGs
        # than outcome_results called for (see VisualizationAgent._execute) —
        # surface that rather than silently claiming full success (never
        # silent, §5): a multi-outcome request that only rendered 1 of 2
        # figures must not read as "done".
        png_generated = (
            output.output_payload.get("r_script_provenance", {}).get("png_generated")
        )
        warning: str | None = None
        if png_generated in (False, "partial"):
            warning = output.output_payload.get("r_script_provenance", {}).get(
                "png_reason"
            ) or "figure generation did not fully complete"
        summary = f"{len(figures)}件の図を生成しました。"
        if warning:
            summary += f"（一部生成できませんでした: {warning}）"
        state.add_turn("assistant", summary)
        frame: dict = {"type": "figures", "execution_id": execution_id, "figures": figures}
        if warning:
            frame["warning"] = warning
        yield frame

    async def _dispatch_report(
        self, turn: DialogTurn, state: ConversationState
    ) -> AsyncIterator[dict]:
        """Draft manuscript sections from the prior results via the Reporting agent."""
        if turn.user_text:
            state.add_turn("user", turn.user_text)
        stats = turn.prior_statistical_results
        if not stats:
            yield {"type": "error", "reason": "no_prior_results_for_report"}
            return

        execution_id = new_execution_id()
        output = await invoke_agent(
            self._services,
            agent_key="reporting",
            agent_id="reporting",
            step_id="ws_chat_report",
            scopes=[
                CapabilityScope.REPORT_COMPILE_MANUSCRIPT,
                CapabilityScope.AUDIT_WRITE_ENTRY,
            ],
            payload={
                "statistical_results": stats,
                "intent_object": turn.intent_object or {},
                "inject_raw_data_rows": False,
            },
            input_schema_ref=_TASK_CONTEXT_SCHEMA_REF,
            execution_id=execution_id,
        )
        if output.status != "success":
            yield {"type": "error", "reason": output.error_message or "report_failed"}
            return

        sections = output.output_payload.get("manuscript_sections") or []
        manuscript_sections = [
            {
                "section_id": s.get("section_id", str(i)),
                "text": s.get("content", ""),
                "is_ai_generated": bool(s.get("llm_generated", False)),
            }
            for i, s in enumerate(sections)
            if isinstance(s, dict)
        ]
        state.add_turn("assistant", f"{len(manuscript_sections)}個の原稿セクションを生成しました。")
        yield {
            "type": "manuscript",
            "execution_id": execution_id,
            "manuscript_sections": manuscript_sections,
        }
