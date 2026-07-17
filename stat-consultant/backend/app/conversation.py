"""Server-side conversation history for the streaming chat (Step 1).

Translated from ``cie/api/conversation.py`` (``ConversationStore``), trimmed to
what the stat-consultant chat needs: the WebSocket ``/ws/consult`` may carry
several turns on one socket, and the assistant reply streams back token by
token, so the server owns the running history rather than trusting the client
to resend it each frame.

Single-user, localhost-bound desktop-style app (SPEC 4.1), so an in-process
dict is sufficient — no external session store. Turns are stored in the shape
the Anthropic Messages API consumes directly (``[{"role", "content"}, ...]``).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field

# Roles we accept on a turn. Anything else is coerced to "user" so a stray value
# can never smuggle a fake "assistant" instruction into the prompt.
_VALID_ROLES = frozenset({"user", "assistant"})

# Keep the running history bounded: recent context is what the reply needs, and
# an unbounded list would grow the prompt (and cost) without limit.
_DEFAULT_HISTORY_LIMIT = 20

# Cap the number of distinct conversations retained (LRU-evicted). One socket
# uses one id; the cap only guards against unbounded growth if ids rotate.
_MAX_CONVERSATIONS = 64


@dataclass
class ConversationState:
    """The running turns of one conversation (oldest→newest)."""

    conversation_id: str
    turns: list[dict] = field(default_factory=list)
    updated_at: float = field(default_factory=time.monotonic)

    def add_turn(self, role: str, content: str) -> None:
        """Append a turn. Blank content is ignored; unknown roles become "user"."""
        content = (content or "").strip()
        if not content:
            return
        safe_role = role if role in _VALID_ROLES else "user"
        self.turns.append({"role": safe_role, "content": content})
        self.updated_at = time.monotonic()

    def history(self, limit: int = _DEFAULT_HISTORY_LIMIT) -> list[dict]:
        """Return the most recent ``limit`` turns (oldest→newest) as a copy.

        The shape matches the Anthropic Messages API ``messages`` argument, so
        it drops straight into the streaming call.
        """
        recent = self.turns[-limit:] if limit > 0 else list(self.turns)
        return [dict(t) for t in recent]


class ConversationStore:
    """In-process, LRU-bounded registry of :class:`ConversationState`.

    Not thread-safe by design: the FastAPI app is single-process and each WS
    turn is handled on the event loop, so accesses never truly overlap.
    """

    def __init__(self, max_conversations: int = _MAX_CONVERSATIONS) -> None:
        self._states: OrderedDict[str, ConversationState] = OrderedDict()
        self._max = max_conversations

    def get_or_create(self, conversation_id: str) -> ConversationState:
        """Return the state for ``conversation_id``, creating it if absent.

        A blank id yields a fresh anonymous state (never shared), so a client
        that omits the id simply gets a non-persistent conversation.
        """
        if not conversation_id:
            return ConversationState(conversation_id="")
        state = self._states.get(conversation_id)
        if state is None:
            state = ConversationState(conversation_id=conversation_id)
            self._states[conversation_id] = state
            self._evict_if_needed()
        else:
            self._states.move_to_end(conversation_id)  # mark most-recently-used
        return state

    def _evict_if_needed(self) -> None:
        while len(self._states) > self._max:
            self._states.popitem(last=False)  # drop least-recently used
