"""Unit coverage for the pure/network-mockable pieces of env_drift.py.

check_env_drift()'s own upsert-against-Postgres logic isn't exercised here --
this project has no SQLite-compatible DB test harness yet (same gap noted on
mobile-backend's GO-3 refresh-token commit: real-Postgres-only, untested in
this environment). _hash and _fetch are pure/network-only, so they're fully
covered; the DB-touching half should get a real-Postgres check (RUN_DB_TESTS
style, matching the other repos' convention) before this ships.
"""

import httpx
import pytest

from src import discord_notify as dn
from src.env_drift import DriftEvent, _fetch, _hash


def test_hash_is_stable_for_identical_content() -> None:
    assert _hash("KEY=value\n") == _hash("KEY=value\n")


def test_hash_changes_when_content_changes() -> None:
    assert _hash("KEY=value\n") != _hash("KEY=other\n")


async def test_fetch_returns_file_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/Cocoa-CUSAR-dev/chatbot/dev/.env.sample"
        return httpx.Response(200, text="LINE_CHANNEL_SECRET=\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        content = await _fetch(client, "chatbot", "dev", ".env.sample")

    assert content == "LINE_CHANNEL_SECRET=\n"


async def test_fetch_returns_none_on_404_instead_of_raising() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        content = await _fetch(client, "mobile-app", "dev", ".env.sample")

    assert content is None


async def test_announce_env_drift_stays_silent_when_nothing_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted = []

    async def _fake_post(content: str) -> None:
        posted.append(content)

    monkeypatch.setattr(dn, "_post", _fake_post)

    await dn.announce_env_drift([])

    assert posted == []


async def test_announce_env_drift_stays_silent_on_first_ever_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A brand-new watched file has nothing to diff against yet -- that's a
    baseline being recorded, not a change someone made.
    """
    posted = []

    async def _fake_post(content: str) -> None:
        posted.append(content)

    monkeypatch.setattr(dn, "_post", _fake_post)

    await dn.announce_env_drift(
        [DriftEvent(repo="chatbot", path=".env.sample", ref="dev", is_new=True)]
    )

    assert posted == []


async def test_announce_env_drift_posts_only_the_actually_changed_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted = []

    async def _fake_post(content: str) -> None:
        posted.append(content)

    monkeypatch.setattr(dn, "_post", _fake_post)

    await dn.announce_env_drift(
        [
            DriftEvent(repo="chatbot", path=".env.sample", ref="dev", is_new=True),
            DriftEvent(
                repo="mobile-backend", path="render.yaml", ref="dev", is_new=False
            ),
        ]
    )

    assert len(posted) == 1
    assert "mobile-backend/render.yaml" in posted[0]
    assert "chatbot/.env.sample" not in posted[0]
