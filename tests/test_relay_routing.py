"""Which address a post goes out from -- the whole point of relay/worker.js.

Render's shared outbound IP was refused by Discord's edge while the same
webhook worked from a laptop, so the fix is not in what we send, only in
where we send it from.
"""

import pytest

from src import discord_notify
from src.discord_notify import _destination

RELAY = "https://cocoa-discord-relay.workers.dev"
WEBHOOK = "https://discord.com/api/webhooks/123/abc"


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discord_notify.settings, "DISCORD_WEBHOOK_URL", WEBHOOK)
    monkeypatch.setattr(discord_notify.settings, "DISCORD_RELAY_URL", "")
    monkeypatch.setattr(discord_notify.settings, "DISCORD_RELAY_SECRET", "")


def test_without_a_relay_it_posts_straight_to_discord() -> None:
    url, headers = _destination()

    assert url == WEBHOOK
    assert headers == {}


def test_with_a_relay_it_posts_there_and_authenticates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discord_notify.settings, "DISCORD_RELAY_URL", RELAY)
    monkeypatch.setattr(discord_notify.settings, "DISCORD_RELAY_SECRET", "s3cret")

    url, headers = _destination()

    assert url == RELAY
    assert headers == {"X-Relay-Secret": "s3cret"}


def test_the_webhook_url_is_never_sent_to_the_relay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The relay holds its own copy as a Worker secret and can reach exactly
    one channel. Passing the webhook through would make the relay's URL as
    dangerous to leak as the webhook itself.
    """
    monkeypatch.setattr(discord_notify.settings, "DISCORD_RELAY_URL", RELAY)
    monkeypatch.setattr(discord_notify.settings, "DISCORD_RELAY_SECRET", "s3cret")

    _, headers = _destination()

    assert WEBHOOK not in str(headers)


def test_half_configured_relay_is_ignored_rather_than_half_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A URL with no secret would be rejected by the Worker with 401 on every
    single message. Posting directly is wrong-ish; posting nowhere is worse.
    """
    monkeypatch.setattr(discord_notify.settings, "DISCORD_RELAY_URL", RELAY)

    url, headers = _destination()

    assert url == WEBHOOK
    assert headers == {}
