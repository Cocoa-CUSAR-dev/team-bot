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
from datetime import UTC, datetime, timedelta

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

# When Discord hands back a Retry-After, honour it instead of knocking again.
# Each rejected request is another 429 on the record, and the block that
# caused this escalates with them -- it went from 491s in the morning to 3242s
# the same evening. Retrying through a cooldown is how a short block becomes a
# long one. In-process (one web service, and a restart only costs one extra
# attempt), so there's nothing to migrate.
_retry_not_before: datetime | None = None


def cooldown_remaining(now: datetime | None = None) -> float:
    """Seconds left before the queue will try Discord again. 0 when clear."""
    if _retry_not_before is None:
        return 0.0
    now = now or datetime.now(UTC)
    return max(0.0, (_retry_not_before - now).total_seconds())


def clear_cooldown() -> None:
    """For tests, and for an operator who knows the block has lifted."""
    global _retry_not_before
    _retry_not_before = None


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
    global _retry_not_before

    now = datetime.now(UTC)
    if _retry_not_before is not None and now < _retry_not_before:
        waiting = (_retry_not_before - now).total_seconds()
        logger.info("outbox: holding off for another %.0fs", waiting)
        return {"sent": 0, "failed": 0, "remaining": -1, "cooldown_seconds": int(waiting)}

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
                retry_after = getattr(e, "retry_after", None)
                if retry_after:
                    _retry_not_before = now + timedelta(seconds=float(retry_after))
                    logger.warning(
                        "outbox: told to wait %.0fs, not retrying until then", retry_after
                    )
                break
            item.sent_at = func.now()
            sent += 1
            await session.commit()

        remaining = len(pending) - sent - failed

    return {"sent": sent, "failed": failed, "remaining": remaining + failed}
