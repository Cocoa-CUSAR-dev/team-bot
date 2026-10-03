"""2026-10-03: Discord answered the deployed service with Retry-After 491
while the same webhook answered a laptop instantly -- an IP-level limit on
shared hosting egress. _post obeyed it literally, so a GitHub delivery sat
open for eight minutes, blew GitHub's ~10s timeout, and was redelivered.
"""

from typing import Self

import httpx
import pytest

from src import discord_notify
from src.discord_notify import MAX_RATE_LIMIT_WAIT, RateLimitedTooLong, _send_now


class _Client:
    """Stands in for httpx.AsyncClient, returning canned responses in order."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.calls = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, *args: object, **kwargs: object) -> httpx.Response:
        response = self._responses[self.calls]
        self.calls += 1
        return response


def _429(retry_after: str) -> httpx.Response:
    return httpx.Response(
        429, headers={"Retry-After": retry_after}, request=httpx.Request("POST", "https://x")
    )


def _204() -> httpx.Response:
    return httpx.Response(204, request=httpx.Request("POST", "https://x"))


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(discord_notify.asyncio, "sleep", fake_sleep)
    return slept


@pytest.mark.anyio
async def test_long_rate_limit_gives_up_instead_of_sleeping(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    client = _Client([_429("491")])
    monkeypatch.setattr(discord_notify.httpx, "AsyncClient", lambda: client)

    with pytest.raises(RateLimitedTooLong) as excinfo:
        await _send_now("hello")

    assert excinfo.value.retry_after == 491
    assert no_sleep == [], "must not sleep through a limit this long"
    assert client.calls == 1


@pytest.mark.anyio
async def test_short_rate_limit_is_still_slept_through_and_retried(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    """The original same-second double-post case must keep working."""
    client = _Client([_429("1"), _204()])
    monkeypatch.setattr(discord_notify.httpx, "AsyncClient", lambda: client)

    await _send_now("hello")

    assert no_sleep == [1.0]
    assert client.calls == 2


@pytest.mark.anyio
async def test_the_cap_is_the_boundary_not_an_approximation(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    client = _Client([_429(str(MAX_RATE_LIMIT_WAIT)), _204()])
    monkeypatch.setattr(discord_notify.httpx, "AsyncClient", lambda: client)

    await _send_now("hello")  # exactly at the cap is allowed

    assert no_sleep == [MAX_RATE_LIMIT_WAIT]
