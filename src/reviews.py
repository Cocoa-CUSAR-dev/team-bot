"""I/O layer around picker.py -- loads current state from the DB, calls the
pure picker, persists the result. Deliberately separate from picker.py so
the selection rule itself needs no DB/mocking to test.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import String, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.grouping import extract_group_key
from src.models import Person, ReviewAssignment
from src.picker import Candidate, pick_reviewer


@dataclass(frozen=True)
class GroupPredecessor:
    """The earlier PR of the same task that decided this assignment -- carried
    back to the caller so the announcement can say WHY someone got it, which
    matters most when the PRs land days apart and the pick would otherwise
    look like the bot ignoring load entirely.
    """

    repo: str
    pr_number: int
    pr_title: str | None
    pr_url: str | None
    assigned_at: datetime


@dataclass(frozen=True)
class AssignmentResult:
    person: Person
    group_key: str | None
    # None when the picker chose normally -- i.e. no key in the title, or this
    # is the first PR of a new key.
    predecessor: GroupPredecessor | None


@dataclass(frozen=True)
class OpenReview:
    repo: str
    pr_number: int
    pr_title: str | None
    pr_url: str | None
    discord_id: str
    assigned_at: datetime


async def _current_loads(session: AsyncSession) -> dict[str, int]:
    """person_id -> current review load.

    One TASK counts once, not one PR. A grouped task can be 5 PRs across 5
    repos (the "Web UI notification" batch of 2026-09-28 was exactly that),
    and counting them linearly would make whoever took it look 5x loaded and
    starve them of everything else for days -- which would punish exactly the
    behaviour grouping exists to encourage. Un-keyed PRs still count one
    apiece, via assignment_id standing in for a group of one.
    """
    result = await session.execute(
        select(
            ReviewAssignment.assignee_id,
            func.count(
                distinct(
                    func.coalesce(
                        ReviewAssignment.group_key,
                        cast(ReviewAssignment.assignment_id, String),
                    )
                )
            ),
        )
        .where(ReviewAssignment.resolved_at.is_(None))
        .group_by(ReviewAssignment.assignee_id)
    )
    return {str(person_id): count for person_id, count in result.all()}


async def _group_holder(
    session: AsyncSession, group_key: str
) -> tuple[Person, GroupPredecessor] | None:
    """Whoever most recently got a PR of this task, if anyone.

    Deliberately NOT filtered to unresolved: a task's PRs trickle in over days
    and the earlier ones are often merged already. Scoping this to still-open
    reviews would scatter the tail of a group right when the convention is
    doing its job.
    """
    row = (
        await session.execute(
            select(ReviewAssignment, Person)
            .join(Person, Person.person_id == ReviewAssignment.assignee_id)
            .where(ReviewAssignment.group_key == group_key)
            .order_by(ReviewAssignment.assigned_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None

    ra, person = row
    return person, GroupPredecessor(
        repo=ra.repo,
        pr_number=ra.pr_number,
        pr_title=ra.pr_title,
        pr_url=ra.pr_url,
        assigned_at=ra.assigned_at,
    )


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
) -> AssignmentResult | None:
    """Group-aware: if the title carries a task key and someone already holds
    that task, it goes straight to them. Otherwise -- no key, new key, or the
    holder turns out to be this PR's own author -- the normal load-balancing
    picker decides, unchanged.
    """
    group_key = extract_group_key(pr_title)

    if group_key is not None:
        held = await _group_holder(session, group_key)
        # Not the author's own PR: a task's PRs are usually all by one person,
        # but a task someone picked up mid-way would otherwise assign them to
        # review themselves.
        if held is not None and held[0].github_username != author_github_username:
            holder, predecessor = held
            session.add(
                ReviewAssignment(
                    repo=repo,
                    pr_number=pr_number,
                    assignee_id=holder.person_id,
                    pr_title=pr_title,
                    pr_url=pr_url,
                    group_key=group_key,
                )
            )
            await session.commit()
            return AssignmentResult(
                person=holder, group_key=group_key, predecessor=predecessor
            )

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
            group_key=group_key,
        )
    )
    await session.commit()

    person = next(p for p in people if str(p.person_id) == chosen.person_id)
    return AssignmentResult(person=person, group_key=group_key, predecessor=None)


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


async def get_person_by_discord_id(session: AsyncSession, discord_id: str) -> Person | None:
    result = await session.execute(select(Person).where(Person.discord_id == discord_id))
    return result.scalars().first()


async def get_open_reviews(
    session: AsyncSession, *, discord_id: str | None = None
) -> list[OpenReview]:
    """Everything still unresolved, oldest first -- feeds the daily reminder
    job (see internal.py).

    `discord_id` narrows it to one person, for /myreviews. Kept as a filter
    on the existing query rather than a second near-identical function, so
    the daily reminder and the slash command can't drift apart on what
    "still open" means.
    """
    conditions = [ReviewAssignment.resolved_at.is_(None)]
    if discord_id is not None:
        conditions.append(Person.discord_id == discord_id)

    rows = await session.execute(
        select(ReviewAssignment, Person)
        .join(Person, Person.person_id == ReviewAssignment.assignee_id)
        .where(*conditions)
        .order_by(ReviewAssignment.assigned_at.asc())
    )
    return [
        OpenReview(
            repo=ra.repo,
            pr_number=ra.pr_number,
            pr_title=ra.pr_title,
            pr_url=ra.pr_url,
            discord_id=person.discord_id,
            assigned_at=ra.assigned_at,
        )
        for ra, person in rows.all()
    ]
