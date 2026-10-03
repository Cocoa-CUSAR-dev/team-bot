"""Receives GitHub's `pull_request` webhook (opened/closed only) -- verifies
the HMAC signature GitHub sends, same discipline as any other webhook
receiver (see the chatbot repo's LINE webhook verification for the sibling
pattern). Configure this URL + GITHUB_WEBHOOK_SECRET on each of the 6 repos'
Settings > Webhooks (or once at the org level, if that's set up).
"""

import hashlib
import hmac
import logging
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from src.config import settings
from src.database import async_session_maker
from src.discord_notify import (
    _send_now,
    announce_assignment,
    announce_no_reviewer_available,
    announce_review_done,
)
from src.outbox import flush
from src.reviews import (
    assign_reviewer,
    get_person_by_github_username,
    is_pr_closed,
    record_closed_pr,
    resolve_reviews,
)

router = APIRouter(prefix="/github", tags=["github"])
logger = logging.getLogger(__name__)


async def _drain_outbox() -> None:
    """Opportunistic retry of anything Discord refused earlier.

    Runs on every delivery so the queue drains the moment a rate limit lifts,
    rather than sitting until the next scheduled flush. Cheap when empty: one
    indexed query returning nothing.
    """
    try:
        result = await flush(_send_now)
        if result["sent"]:
            logger.info("outbox: delivered %s queued message(s)", result["sent"])
    except Exception:
        logger.exception("outbox flush failed")


async def _safe_announce(
    announce: Callable[..., Awaitable[None]], **kwargs: object
) -> None:
    """Every Discord post runs through here, after the response has gone
    back to GitHub. A failure must stay a log line: the DB is already the
    source of truth, and anything that reaches GitHub as an error becomes a
    redelivery, which re-runs the handler and double-assigns.
    """
    try:
        await announce(**kwargs)
    except Exception:
        logger.exception(
            "%s failed to post to Discord for %s#%s (the DB change still stands)",
            getattr(announce, "__name__", announce),
            kwargs.get("repo"),
            kwargs.get("pr_number"),
        )


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
    background: BackgroundTasks,
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

    # Before anything else: whatever is queued is older than this event,
    # and order is the whole point of the queue.
    background.add_task(_drain_outbox)

    if action == "opened":
        async with async_session_maker() as session:
            # The close may already have been processed -- these two events
            # can be seconds apart and arrive out of order (chatbot#72 was
            # merged 4s before its own `opened` finished writing). Assigning
            # now would create a review nothing can ever resolve, so it would
            # haunt the daily reminder forever.
            if await is_pr_closed(session, repo=repo, pr_number=pr_number):
                logger.info(
                    "skipping assignment for %s#%s -- already closed before this "
                    "`opened` event was processed",
                    repo,
                    pr_number,
                )
                return {"status": "already-closed"}

            assignment = await assign_reviewer(
                session,
                repo=repo,
                pr_number=pr_number,
                author_github_username=pr["user"]["login"],
                pr_title=pr["title"],
                pr_url=pr["html_url"],
            )
        # The DB write above is already committed at this point -- it's the
        # source of truth (see models.py), Discord is just an announcement.
        # It runs AFTER the response goes back to GitHub, because GitHub gives
        # a delivery ~10s before calling it failed and redelivering it -- and
        # a redelivery re-runs assign_reviewer and double-assigns. Posting
        # inline risked exactly that on 2026-10-03, when a rate-limited post
        # held the request open for minutes.
        if assignment is None:
            background.add_task(
                _safe_announce,
                announce_no_reviewer_available,
                repo=repo,
                pr_number=pr_number,
                pr_title=pr["title"],
            )
        else:
            background.add_task(
                _safe_announce,
                announce_assignment,
                repo=repo,
                pr_number=pr_number,
                pr_title=pr["title"],
                pr_url=pr["html_url"],
                reviewer_discord_id=assignment.person.discord_id,
                author_github_username=pr["user"]["login"],
                group_key=assignment.group_key,
                predecessor=assignment.predecessor,
            )
    elif action == "closed":
        author_github_username = pr["user"]["login"]
        async with async_session_maker() as session:
            # Recorded whether or not there's anything to resolve right now --
            # that's the whole point, a late `opened` needs to find this.
            await record_closed_pr(session, repo=repo, pr_number=pr_number)
            resolved_reviewers = await resolve_reviews(session, repo=repo, pr_number=pr_number)
            author = await get_person_by_github_username(session, author_github_username)

        # Praise only fires on an actual merge -- a closed-without-merging
        # PR didn't really get "reviewed through", so celebrating it would
        # be a lie. resolved_reviewers is usually exactly one person.
        if pr.get("merged") and resolved_reviewers:
            for reviewer in resolved_reviewers:
                # Same reasoning as the "opened" branch above: resolve_reviews
                # already committed (marked resolved_at), so the post happens
                # after the response and can't delay or fail this delivery.
                background.add_task(
                    _safe_announce,
                    announce_review_done,
                    repo=repo,
                    pr_number=pr_number,
                    pr_title=pr["title"],
                    pr_url=pr["html_url"],
                    reviewer_display_name=reviewer.display_name,
                    reviewer_github_username=reviewer.github_username,
                    author_discord_id=author.discord_id if author else None,
                    author_github_username=author_github_username,
                )

    return {"status": "ok"}
