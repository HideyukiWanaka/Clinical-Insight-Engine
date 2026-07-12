"""CIE Platform — server-side conversation session (Phase 2 chat streaming).

Phase 1 kept the chat history entirely client-side: ``ChatPane`` rebuilt a
``conversation_history`` array on every ``/api/intent`` / ``/api/propose`` call.
Phase 2 introduces a *streaming* chat over ``WS /ws/chat`` (cie/api/routes/
ws_chat.py), where the same socket may carry several turns and the assistant
reply streams in token by token. For the streamed explanation to reflect the
whole dialogue, the server must own the running history rather than trust the
client to resend it each frame.

``ConversationState`` holds that running history (role + text turns only — never
raw patient data, consistent with the var_n / PII-scan boundary the agents
already enforce). ``ConversationStore`` keeps one state per ``conversation_id``.
Single-user, 127.0.0.1-bound server (ADR-0005), so an in-process dict mirrors
the existing ``app.state.dataset_context`` pattern (cie/api/deps.py) — no
external session store is warranted.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field

# Roles we accept on a turn. Anything else is coerced to "user" so a stray value
# can never smuggle a fake "assistant"/"system" instruction into the prompt.
_VALID_ROLES = frozenset({"user", "assistant"})

# Keep the running history bounded: the streamed explanation only needs recent
# context, and an unbounded list would grow the prompt (and cost) without limit.
_DEFAULT_HISTORY_LIMIT = 12
# Cap the number of distinct conversations retained (LRU-evicted). A single
# browser session uses one id; the cap only guards against unbounded growth if
# a client rotates ids.
_MAX_CONVERSATIONS = 64


@dataclass
class ConversationState:
    """The running turns of one chat conversation (oldest→newest)."""

    conversation_id: str
    turns: list[dict] = field(default_factory=list)
    updated_at: float = field(default_factory=time.monotonic)

    def add_turn(self, role: str, text: str) -> None:
        """Append a turn. Blank text is ignored; unknown roles become "user"."""
        text = (text or "").strip()
        if not text:
            return
        safe_role = role if role in _VALID_ROLES else "user"
        self.turns.append({"role": safe_role, "text": text})
        self.updated_at = time.monotonic()

    def history(self, limit: int = _DEFAULT_HISTORY_LIMIT) -> list[dict]:
        """Return the most recent ``limit`` turns (oldest→newest) as a copy.

        The shape matches the ``conversation_history`` the Statistics agent
        already consumes (``[{"role", "text"}, ...]``), so it drops straight
        into the propose payload.
        """
        recent = self.turns[-limit:] if limit > 0 else list(self.turns)
        return [dict(t) for t in recent]


class ConversationStore:
    """In-process, LRU-bounded registry of :class:`ConversationState`.

    Not thread-safe by design: the FastAPI app is single-process and each WS
    turn is handled on the event loop, so accesses never truly overlap.
    """

    def __init__(self, max_conversations: int = _MAX_CONVERSATIONS) -> None:
        """Create an empty store retaining at most ``max_conversations`` states."""
        self._states: OrderedDict[str, ConversationState] = OrderedDict()
        self._max = max_conversations

    def get_or_create(self, conversation_id: str) -> ConversationState:
        """Return the state for ``conversation_id``, creating it if absent.

        A blank/None id yields a fresh anonymous state (never shared), so a
        client that omits the id simply gets a non-persistent conversation.
        """
        if not conversation_id:
            return ConversationState(conversation_id="")
        state = self._states.get(conversation_id)
        if state is None:
            state = ConversationState(conversation_id=conversation_id)
            self._states[conversation_id] = state
            self._evict_if_needed()
        else:
            # Mark as most-recently used for LRU eviction.
            self._states.move_to_end(conversation_id)
        return state

    def _evict_if_needed(self) -> None:
        while len(self._states) > self._max:
            self._states.popitem(last=False)  # drop least-recently used
