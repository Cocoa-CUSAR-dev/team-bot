"""_post's 429 handling -- see the 2026-09-01 database#32/chatbot#46 incident
in discord_notify.py's comment: two PRs opened moments apart both posting to
the same Discord webhook tripped its rate limit, and the resulting
unhandled HTTPStatusError crashed the whole webhook request as a 500.
"""

import httpx
import pytest

from src import discord_notify as dn


class _ScriptedHandler:
    """Returns each status in `statuses` in order, one per request."""

    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        status = self._statuses.pop(0)
        if status == 429:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"retry_after": 0})
        return httpx.Response(status)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(dn.asyncio, "sleep", _instant)


def _install(monkeypatch: pytest.MonkeyPatch, statuses: list[int]) -> _ScriptedHandler:
    handler = _ScriptedHandler(statuses)
    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.AsyncClient

    class _ClientWithMockTransport(real_client_cls):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(dn.httpx, "AsyncClient", _ClientWithMockTransport)
    return handler


async def test_single_429_is_retried_once_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _install(monkeypatch, [429, 204])

    await dn._post("hi")  # must not raise

    assert handler.calls == 2


async def test_a_second_consecutive_429_still_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _install(monkeypatch, [429, 429])

    with pytest.raises(httpx.HTTPStatusError):
        await dn._post("hi")

    # Only one retry, not an infinite/unbounded loop.
    assert handler.calls == 2


async def test_a_non_429_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _install(monkeypatch, [500])

    with pytest.raises(httpx.HTTPStatusError):
        await dn._post("hi")

    assert handler.calls == 1


def test_rate_limit_wait_prefers_the_header() -> None:
    response = httpx.Response(429, headers={"Retry-After": "2.5"}, json={"retry_after": 9})
    assert dn._rate_limit_wait_seconds(response) == 2.5


def test_rate_limit_wait_falls_back_to_body() -> None:
    response = httpx.Response(429, json={"retry_after": 1.25})
    assert dn._rate_limit_wait_seconds(response) == 1.25


def test_rate_limit_wait_falls_back_to_a_default_when_neither_is_usable() -> None:
    response = httpx.Response(429, content=b"not json")
    assert dn._rate_limit_wait_seconds(response) == 1.0
