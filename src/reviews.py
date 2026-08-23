"""I/O layer around picker.py -- loads current state from the DB, calls the
pure picker, persists the result. Deliberately separate from picker.py so
the selection rule itself needs no DB/mocking to test.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Person, ReviewAssignment
from src.picker import Candidate, pick_reviewer


@dataclass(frozen=True)
class OpenReview:
    repo: str
    pr_number: int
    pr_title: str | None
    pr_url: str | None
    discord_id: str


async def _current_loads(session: AsyncSession) -> dict[str, int]:
    """person_id -> count of open (unresolved) review assignments."""
    result = await session.execute(
        select(ReviewAssignment.assignee_id, func.count())
        .where(ReviewAssignment.resolved_at.is_(None))
        .group_by(ReviewAssignment.assignee_id)
    )
    return {str(person_id): count for person_id, count in result.all()}


async def get_person_by_github_username(session: AsyncSession, github_username: str) -> Person | None:
    result = await session.execute(select(Person).where(Person.github_username == github_username))
    return result.scalars().first()


async def _last_assigned_github_username(session: AsyncSession) -> str | None:
    """Whoever got the most recent assignment, globally (any repo, resolved
    or not) -- used to break ties away from an immediate repeat. Not scoped
    to one repo: the point is spreading load across the whole team, not per
    repo.
    """
    result = await session.execute(
        select(Person.github_username)
        .join(ReviewAssignment, ReviewAssignment.assignee_id == Person.person_id)
        .order_by(ReviewAssignment.assigned_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def assign_reviewer(
    session: AsyncSession,
    *,
    repo: str,
    pr_number: int,
    author_github_username: str,
    pr_title: str | None = None,
    pr_url: str | None = None,
) -> Person | None:
    people = (await session.execute(select(Person))).scalars().all()
    loads = await _current_loads(session)
    last_assigned = await _last_assigned_github_username(session)

    candidates = [
        Candidate(
            person_id=str(p.person_id),
            github_username=p.github_username,
            open_review_count=loads.get(str(p.person_id), 0),
        )
        for p in people
    ]

    chosen = pick_reviewer(
        candidates=candidates,
        author_github_username=author_github_username,
        last_assigned_github_username=last_assigned,
    )
    if chosen is None:
        return None

    session.add(
        ReviewAssignment(
            repo=repo,
            pr_number=pr_number,
            assignee_id=chosen.person_id,
            pr_title=pr_title,
            pr_url=pr_url,
        )
    )
    await session.commit()

    return next(p for p in people if str(p.person_id) == chosen.person_id)


async def resolve_reviews(session: AsyncSession, *, repo: str, pr_number: int) -> list[Person]:
    """Called on PR close (merged or not) -- closes any open assignment for
    this PR and returns who those assignments belonged to (so the caller can
    post a "thanks for reviewing" message -- see github_webhook.py). A PR
    usually has exactly one open assignment, but this doesn't assume it.
    """
    open_assignments = (
        (
            await session.execute(
                select(ReviewAssignment).where(
                    ReviewAssignment.repo == repo,
                    ReviewAssignment.pr_number == pr_number,
                    ReviewAssignment.resolved_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not open_assignments:
        return []

    assignee_ids = [a.assignee_id for a in open_assignments]
    for a in open_assignments:
        a.resolved_at = func.now()
    await session.commit()

    people = (
        (await session.execute(select(Person).where(Person.person_id.in_(assignee_ids))))
        .scalars()
        .all()
    )
    return list(people)


async def get_open_reviews(session: AsyncSession) -> list[OpenReview]:
    """Everything still unresolved, oldest first -- feeds the daily reminder
    job (see scheduler.py).
    """
    rows = await session.execute(
        select(ReviewAssignment, Person)
        .join(Person, Person.person_id == ReviewAssignment.assignee_id)
        .where(ReviewAssignment.resolved_at.is_(None))
        .order_by(ReviewAssignment.assigned_at.asc())
    )
    return [
        OpenReview(
            repo=ra.repo,
            pr_number=ra.pr_number,
            pr_title=ra.pr_title,
            pr_url=ra.pr_url,
            discord_id=person.discord_id,
        )
        for ra, person in rows.all()
    ]
