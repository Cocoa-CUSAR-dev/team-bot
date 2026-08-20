"""Receives GitHub's `pull_request` webhook (opened/closed only) -- verifies
the HMAC signature GitHub sends, same discipline as any other webhook
receiver (see the chatbot repo's LINE webhook verification for the sibling
pattern). Configure this URL + GITHUB_WEBHOOK_SECRET on each of the 6 repos'
Settings > Webhooks (or once at the org level, if that's set up).
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request, status

from src.config import settings
from src.database import async_session_maker
from src.discord_bot import announce_assignment, announce_no_reviewer_available
from src.reviews import assign_reviewer, resolve_reviews

router = APIRouter(prefix="/github", tags=["github"])
logger = logging.getLogger(__name__)


def _verify_signature(body: bytes, signature_header: str | None) -> None:
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing signature")

    expected = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    got = signature_header.removeprefix("sha256=")
    if not hmac.compare_digest(expected, got):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad signature")


@router.post("/webhook", status_code=200)
async def webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, str]:
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    if x_github_event != "pull_request":
        return {"status": "ignored"}

    payload = await request.json()
    action = payload.get("action")
    pr = payload["pull_request"]
    repo = payload["repository"]["full_name"]
    pr_number = pr["number"]

    if action == "opened":
        async with async_session_maker() as session:
            reviewer = await assign_reviewer(
                session,
                repo=repo,
                pr_number=pr_number,
                author_github_username=pr["user"]["login"],
            )
        if reviewer is None:
            await announce_no_reviewer_available(repo=repo, pr_number=pr_number, pr_title=pr["title"])
        else:
            await announce_assignment(
                repo=repo,
                pr_number=pr_number,
                pr_title=pr["title"],
                pr_url=pr["html_url"],
                reviewer_discord_username=reviewer.discord_username,
                author_github_username=pr["user"]["login"],
            )
    elif action == "closed":
        async with async_session_maker() as session:
            await resolve_reviews(session, repo=repo, pr_number=pr_number)

    return {"status": "ok"}
