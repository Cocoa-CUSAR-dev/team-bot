"""Endpoints meant to be triggered by something we control (a GitHub Actions
cron), not GitHub's own webhook -- separate router, separate auth (a plain
shared-secret header, not GitHub's HMAC scheme) so the two trust boundaries
don't get mixed up.
"""

import hmac

from fastapi import APIRouter, Header, HTTPException, status

from src.config import settings
from src.database import async_session_maker
from src.discord_notify import announce_daily_reminder
from src.reviews import get_open_reviews

router = APIRouter(prefix="/internal", tags=["internal"])


def _verify_secret(provided: str | None) -> None:
    if not provided or not hmac.compare_digest(provided, settings.INTERNAL_TRIGGER_SECRET):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad or missing secret")


@router.post("/daily-reminder", status_code=200)
async def daily_reminder(x_internal_secret: str | None = Header(default=None)) -> dict[str, str]:
    _verify_secret(x_internal_secret)

    async with async_session_maker() as session:
        open_reviews = await get_open_reviews(session)
    await announce_daily_reminder(open_reviews)

    return {"status": "ok", "open_count": str(len(open_reviews))}
