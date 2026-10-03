"""The queue exists so a message Discord refuses isn't just gone -- that was
the actual damage on 2026-10-03, not the rate limit itself.
"""

from datetime import UTC, datetime, timedelta
from typing import Self

import pytest

from src import discord_notify, outbox


class _FakeResult:
    def __init__(self, items: list) -> None:
        self._items = items

    def scalars(self) -> Self:
        return self

    def all(self) -> list:
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class _FakeSession:
    """Just enough AsyncSession for outbox: hand back canned rows, count commits."""

    def __init__(self, items: list | None = None) -> None:
        self.items = items or []
        self.commits = 0
        self.added: list = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement: object) -> _FakeResult:
        return _FakeResult(self.items)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


class _Item:
    def __init__(self, content: str) -> None:
        self.content = content
        self.sent_at = None
        self.attempts = 0
        self.last_error = None


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str | None]]:
    """Captures what would be written to pending_announcement."""
    written: list[tuple[str, str | None]] = []

    async def fake_enqueue(session, content, *, error=None):
        written.append((content, error))

    monkeypatch.setattr(discord_notify, "async_session_maker", _FakeSession)
    monkeypatch.setattr(discord_notify.outbox, "enqueue", fake_enqueue)
    return written


@pytest.fixture
def nothing_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_has_pending(session) -> bool:
        return False

    monkeypatch.setattr(discord_notify.outbox, "has_pending", fake_has_pending)


@pytest.mark.anyio
async def test_a_failed_post_is_queued_rather_than_lost(
    monkeypatch: pytest.MonkeyPatch, queued: list, nothing_pending: None
) -> None:
    async def boom(content: str) -> None:
        raise discord_notify.RateLimitedTooLong(491)

    monkeypatch.setattr(discord_notify, "_send_now", boom)

    await discord_notify._post("ping kwan")  # must not raise

    assert len(queued) == 1
    content, error = queued[0]
    assert content == "ping kwan"
    assert "RateLimitedTooLong" in error


@pytest.mark.anyio
async def test_a_successful_post_queues_nothing(
    monkeypatch: pytest.MonkeyPatch, queued: list, nothing_pending: None
) -> None:
    sent: list[str] = []

    async def ok(content: str) -> None:
        sent.append(content)

    monkeypatch.setattr(discord_notify, "_send_now", ok)

    await discord_notify._post("ping kwan")

    assert sent == ["ping kwan"]
    assert queued == []


@pytest.mark.anyio
async def test_messages_queue_behind_an_earlier_undelivered_one(
    monkeypatch: pytest.MonkeyPatch, queued: list
) -> None:
    """Order matters: "ต่อจาก X ที่ถืออยู่" has to arrive after the message it
    refers to, so nothing may overtake a stuck message even if Discord would
    accept it right now.
    """

    async def fake_has_pending(session) -> bool:
        return True

    monkeypatch.setattr(discord_notify.outbox, "has_pending", fake_has_pending)

    sent: list[str] = []

    async def ok(content: str) -> None:
        sent.append(content)

    monkeypatch.setattr(discord_notify, "_send_now", ok)

    await discord_notify._post("second message")

    assert sent == [], "must not overtake the queue"
    assert queued == [("second message", None)]


@pytest.mark.anyio
async def test_flush_sends_in_order_and_marks_them_sent(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    items = [_Item("one"), _Item("two")]
    monkeypatch.setattr(outbox, "async_session_maker", lambda: _FakeSession(items))

    sent: list[str] = []

    async def send(content: str) -> None:
        sent.append(content)

    result = await outbox.flush(send)

    assert sent == ["one", "two"]
    assert all(item.sent_at is not None for item in items)
    assert result == {"sent": 2, "failed": 0, "remaining": 0}


@pytest.mark.anyio
async def test_flush_stops_at_the_first_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pushing past a failure would deliver the third message before the
    second, and when the cause is a rate limit the rest would fail anyway --
    hammering through them is what deepened the limit in the first place.
    """
    items = [_Item("one"), _Item("two"), _Item("three")]
    monkeypatch.setattr(outbox, "async_session_maker", lambda: _FakeSession(items))

    async def send(content: str) -> None:
        if content == "two":
            raise RuntimeError("429 again")

    result = await outbox.flush(send)

    assert items[0].sent_at is not None
    assert items[2].sent_at is None, "must not overtake the one that failed"
    assert items[1].attempts == 1
    assert "429 again" in items[1].last_error
    assert result == {"sent": 1, "failed": 1, "remaining": 2}


# Not covered here: the MAX_ATTEMPTS cut-off that stops a permanently-bad
# message blocking the queue. It lives in the WHERE clause, and the fake
# session above returns whatever rows it's given without filtering, so a test
# written against it would assert the fake's behaviour rather than the query's.
# Verified by hand against the real DB instead.


@pytest.mark.anyio
async def test_a_retry_after_stops_the_queue_knocking_again(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each rejected request is another 429 on the record, and the block
    escalates with them -- 491s in the morning became 3242s by evening.
    """
    outbox.clear_cooldown()
    items = [_Item("one")]
    monkeypatch.setattr(outbox, "async_session_maker", lambda: _FakeSession(items))

    attempts: list[str] = []

    async def rate_limited(content: str) -> None:
        attempts.append(content)
        raise discord_notify.RateLimitedTooLong(3242)

    first = await outbox.flush(rate_limited)
    assert first["failed"] == 1
    assert len(attempts) == 1

    second = await outbox.flush(rate_limited)

    assert len(attempts) == 1, "must not knock again during the cooldown"
    assert second["cooldown_seconds"] > 3000
    outbox.clear_cooldown()


@pytest.mark.anyio
async def test_the_queue_resumes_once_the_cooldown_passes(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    outbox.clear_cooldown()
    items = [_Item("one")]
    monkeypatch.setattr(outbox, "async_session_maker", lambda: _FakeSession(items))

    async def rate_limited(content: str) -> None:
        raise discord_notify.RateLimitedTooLong(1)

    await outbox.flush(rate_limited)
    # Pretend the wait has elapsed rather than actually sleeping for it.
    outbox._retry_not_before = datetime.now(UTC) - timedelta(seconds=1)

    sent: list[str] = []

    async def ok(content: str) -> None:
        sent.append(content)

    result = await outbox.flush(ok)

    assert sent == ["one"]
    assert result["sent"] == 1
    outbox.clear_cooldown()


def test_cooldown_remaining_is_zero_when_nothing_is_blocking() -> None:
    outbox.clear_cooldown()

    assert outbox.cooldown_remaining() == 0.0
