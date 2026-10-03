"""Durable queue for Discord messages.

Everything else here already survives a Discord outage: the assignment is
committed before anything is posted, and /myreviews reads from the DB. The
post itself was the one step with no record of its own, so when Discord
rate-limited the deployed service for minutes at a time (2026-10-03, 429 with
Retry-After 491 while the same webhook answered a laptop instantly), the
message was simply gone and the team was left wondering whether the bot had
died.

Order is preserved on purpose: once anything is queued, later messages queue
behind it rather than overtaking it. Review pings arriving out of order would
be worse than arriving late -- "ต่อจาก X ที่ถืออยู่" has to come after the
message it refers to.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import async_session_maker
from src.models import PendingAnnouncement

logger = logging.getLogger(__name__)

# After this many failures a message is left behind rather than blocking the
# queue forever. A message Discord keeps rejecting is almost certainly
# malformed (too long, bad mention), not rate-limited -- retrying it until the
# end of time would hold every later message hostage to one bad one.
MAX_ATTEMPTS = 5


async def enqueue(session: AsyncSession, content: str, *, error: str | None = None) -> None:
    session.add(PendingAnnouncement(content=content, last_error=error))
    await session.commit()


async def has_pending(session: AsyncSession) -> bool:
    row = await session.execute(
        select(PendingAnnouncement.announcement_id)
        .where(
            PendingAnnouncement.sent_at.is_(None),
            PendingAnnouncement.attempts < MAX_ATTEMPTS,
        )
        .limit(1)
    )
    return row.scalars().first() is not None


async def flush(send) -> dict[str, int]:
    """Try the queue oldest-first, stopping at the first failure.

    Stopping rather than continuing is deliberate twice over: it keeps the
    order intact, and when the cause is a rate limit the remaining messages
    would fail too -- hammering through them is what deepened the limit in the
    first place.

    `send` is injected rather than imported so this module doesn't depend on
    discord_notify, which imports plenty of its own things; it also makes the
    whole loop testable without patching module internals.
    """
    sent = failed = 0
    async with async_session_maker() as session:
        pending = (
            (
                await session.execute(
                    select(PendingAnnouncement)
                    .where(
                        PendingAnnouncement.sent_at.is_(None),
                        PendingAnnouncement.attempts < MAX_ATTEMPTS,
                    )
                    .order_by(PendingAnnouncement.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

        for item in pending:
            try:
                await send(item.content)
            except Exception as e:  # noqa: BLE001 -- recorded on the row, not swallowed
                item.attempts += 1
                item.last_error = f"{type(e).__name__}: {e}"[:500]
                failed += 1
                await session.commit()
                logger.warning(
                    "outbox stalled after %s sent: %s (attempt %s of %s)",
                    sent,
                    item.last_error,
                    item.attempts,
                    MAX_ATTEMPTS,
                )
                break
            item.sent_at = func.now()
            sent += 1
            await session.commit()

        remaining = len(pending) - sent - failed

    return {"sent": sent, "failed": failed, "remaining": remaining + failed}
