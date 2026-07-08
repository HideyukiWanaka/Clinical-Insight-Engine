"""Unit tests for cie.api.rate_limit.RateLimitMiddleware (OWASP A04:2025).

Exercises the fixed-window matcher and counter directly rather than through
a full app, since the behaviour only depends on path + client host + clock.
"""

from __future__ import annotations

from cie.api.rate_limit import RateLimitMiddleware


def test_match_returns_configured_limit_for_known_prefix() -> None:
    result = RateLimitMiddleware._match("/api/intent")
    assert result == ("/api/intent", 10, 60)


def test_match_returns_none_for_unlisted_path() -> None:
    assert RateLimitMiddleware._match("/api/files") is None


def test_match_is_prefix_based() -> None:
    result = RateLimitMiddleware._match("/api/run/status")
    assert result == ("/api/run", 20, 60)
