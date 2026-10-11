"""Answers "why did it pick them, and who's next" without anyone reading code.

The picker's rules are explainable but invisible: the team sees a name and a
กวนๆ line, and when the same person gets two in a row it looks broken (it
did on 2026-08-20, and the answer then took a DB query to establish). This
reads the same numbers the picker reads and shows them.

It never re-implements the selection rule -- it calls picker.shortlist, the
exact function pick_reviewer uses, so a prediction can't disagree with what
actually happens.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Person
from src.picker import Candidate, shortlist
from src.reviews import (
    _last_assigned_github_username,
    open_load_points,
    recent_load_points,
)


@dataclass(frozen=True)
class Standing:
    display_name: str
    github_username: str
    discord_id: str
    recent_load: float
    open_load: float


@dataclass(frozen=True)
class Outcome:
    """Who a PR by `author` would go to, and how likely each name is."""

    author: Standing
    finalists: list[Standing]


@dataclass(frozen=True)
class Prediction:
    standings: list[Standing]
    outcomes: list[Outcome]
    last_assigned: str | None
    window_days: int


async def predict(session: AsyncSession, *, window_days: int) -> Prediction:
    people = (await session.execute(select(Person))).scalars().all()
    recent = await recent_load_points(session)
    still_open = await open_load_points(session)
    last_assigned = await _last_assigned_github_username(session)

    standings = [
        Standing(
            display_name=p.display_name,
            github_username=p.github_username,
            discord_id=p.discord_id,
            recent_load=recent.get(str(p.person_id), 0.0),
            open_load=still_open.get(str(p.person_id), 0.0),
        )
        for p in people
    ]
    standings.sort(key=lambda s: (s.recent_load, s.open_load, s.display_name))

    by_username = {s.github_username: s for s in standings}
    candidates = [
        Candidate(
            person_id=s.github_username,
            github_username=s.github_username,
            recent_load=s.recent_load,
            open_load=s.open_load,
        )
        for s in standings
    ]

    # One outcome per possible author, because the author is excluded from
    # their own PR -- there is no single "next reviewer", only "next reviewer
    # if X opens it". Four people, so four lines; this stays readable exactly
    # as long as the team stays small, which is the same assumption the seeded
    # roster already makes.
    outcomes = [
        Outcome(
            author=author,
            finalists=[
                by_username[c.github_username]
                for c in shortlist(
                    candidates=candidates,
                    author_github_username=author.github_username,
                    last_assigned_github_username=last_assigned,
                )
            ],
        )
        for author in standings
    ]

    return Prediction(
        standings=standings,
        outcomes=outcomes,
        last_assigned=last_assigned,
        window_days=window_days,
    )
