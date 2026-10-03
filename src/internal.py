"""Endpoints meant to be triggered by something we control (a GitHub Actions
cron), not GitHub's own webhook -- separate router, separate auth (a plain
shared-secret header, not GitHub's HMAC scheme) so the two trust boundaries
don't get mixed up.
"""

import hmac
import traceback

import httpx
from fastapi import APIRouter, Header, HTTPException, status

from src.config import settings
from src.database import async_session_maker
from src.discord_notify import _send_now, announce_daily_reminder
from src.outbox import cooldown_remaining, flush
from src.reviews import get_open_reviews

router = APIRouter(prefix="/internal", tags=["internal"])


def _verify_secret(provided: str | None) -> None:
    if not provided or not hmac.compare_digest(provided, settings.INTERNAL_TRIGGER_SECRET):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad or missing secret")


@router.post("/flush-outbox", status_code=200)
async def flush_outbox(
    x_internal_secret: str | None = Header(default=None),
) -> dict[str, int]:
    """Retry queued messages. Called by cron, and opportunistically on every
    GitHub webhook -- the queue drains as soon as the rate limit lifts rather
    than waiting for the next scheduled run.
    """
    _verify_secret(x_internal_secret)
    result = await flush(_send_now)
    # Surfaced so "nothing happened" can be told apart from "deliberately
    # waiting out a block" without reading logs.
    result["cooldown_seconds"] = int(cooldown_remaining())
    return result


@router.post("/test-announce", status_code=200)
async def test_announce(
    x_internal_secret: str | None = Header(default=None),
) -> dict[str, object]:
    """Can this service actually deliver a message to Discord right now?

    Goes through `_send_now`, NOT `_post`: _post's whole job is to swallow a
    failure and queue the message, which is right in production and useless in
    a diagnostic -- it would answer "fine" while nothing reaches the channel.
    This reports what Discord really said.

    Posts a visibly-labelled test message to the channel when it succeeds.
    """
    _verify_secret(x_internal_secret)

    try:
        await _send_now("🔧 ทดสอบระบบส่งข้อความ (ไม่ใช่ PR จริง)")
    except Exception as e:  # noqa: BLE001 -- reporting it IS the point here
        return {
            "delivered": False,
            "error_type": type(e).__name__,
            "error": str(e)[:500],
            "traceback": traceback.format_exc()[-1500:],
        }

    return {"delivered": True}


@router.post("/webhook-check", status_code=200)
async def webhook_check(
    x_internal_secret: str | None = Header(default=None),
) -> dict[str, object]:
    """Is the configured Discord webhook URL actually usable from here?

    Exists because of 2026-10-01/02: GitHub webhooks arrived, assignments were
    written, grouping worked -- and not one message reached Discord, while
    /myreviews kept answering fine. That split points at the one thing only
    the announcement path does, an OUTBOUND call to discord.com, but the only
    evidence was a logged traceback in a dashboard nobody wants to dig through
    at 1am.

    Uses GET on the webhook URL, which Discord answers with the webhook's own
    metadata -- so this verifies the URL and token without posting anything to
    the channel. The reply never includes the token: whoever can call this
    could already read the service's env, but it would end up pasted into
    chat, and a webhook token is enough to post as the bot.
    """
    _verify_secret(x_internal_secret)

    url = settings.DISCORD_WEBHOOK_URL
    # ".../webhooks/<id>/<token>" -- the id is safe to show and is what you
    # compare against the Discord UI; the token is not.
    parts = url.rstrip("/").split("/")
    webhook_id = parts[-2] if len(parts) >= 2 else None
    token_length = len(parts[-1]) if parts else 0

    report: dict[str, object] = {
        "configured": bool(url),
        "webhook_id": webhook_id,
        "token_length": token_length,
        "host": url.split("/")[2] if url.count("/") >= 2 else None,
    }

    if not url:
        report["result"] = "DISCORD_WEBHOOK_URL is not set"
        return report

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
    except httpx.HTTPError as e:  # network/DNS/TLS -- the thing logs would hide
        report["result"] = f"request failed: {type(e).__name__}: {e}"
        return report

    report["discord_status"] = response.status_code
    if response.status_code == 200:
        body = response.json()
        report["result"] = "ok"
        report["channel_id"] = body.get("channel_id")
        report["webhook_name"] = body.get("name")
    elif response.status_code in (401, 403):
        report["result"] = "token rejected -- the URL's token is wrong or was reset"
    elif response.status_code == 404:
        report["result"] = "webhook does not exist -- deleted, or wrong id"
    elif response.status_code == 429:
        report["result"] = "rate limited right now"
        report["retry_after"] = response.headers.get("Retry-After")
    else:
        report["result"] = f"unexpected: {response.text[:200]}"

    return report


@router.post("/daily-reminder", status_code=200)
async def daily_reminder(x_internal_secret: str | None = Header(default=None)) -> dict[str, str]:
    _verify_secret(x_internal_secret)

    async with async_session_maker() as session:
        open_reviews = await get_open_reviews(session)
    await announce_daily_reminder(open_reviews)

    return {"status": "ok", "open_count": str(len(open_reviews))}
