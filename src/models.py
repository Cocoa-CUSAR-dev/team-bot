"""Two tables only.

`person` is seeded directly (see seed.py) -- 4 fixed teammates, no self-serve
linking command needed for a team this size.

`review_assignment` is an event log, not a mutable counter. Someone's
current review load is COUNT(*) WHERE resolved_at IS NULL -- derived, not
stored -- so a missed/duplicated webhook event can't leave a counter
permanently wrong the way an increment/decrement field could.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class Person(Base):
    __tablename__ = "person"

    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # A real <@ID> mention needs the numeric snowflake ID, not the username --
    # required now that posting goes through a plain incoming webhook
    # (stateless, no member-list lookup available like a real bot client
    # would have). Developer Mode -> right-click a person -> Copy User ID.
    discord_id: Mapped[str] = mapped_column(String, unique=True)
    github_username: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str] = mapped_column(String)


class EnvSnapshot(Base):
    """Last-known SHA-256 of one watched env-declaration file (a repo's
    .env.sample or render.yaml -- never a real .env, those aren't in git).
    One row per (repo, path); checked daily, see env_drift.py. A changed
    hash means someone edited that file since the last check -- doesn't
    (can't) see secret values changed only in Render/GitHub's dashboard,
    since those never touch a git-tracked file at all.
    """

    __tablename__ = "env_snapshot"

    repo: Mapped[str] = mapped_column(String, primary_key=True)
    path: Mapped[str] = mapped_column(String, primary_key=True)
    sha256: Mapped[str] = mapped_column(String)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReviewAssignment(Base):
    __tablename__ = "review_assignment"

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    repo: Mapped[str] = mapped_column(String)
    pr_number: Mapped[int]
    assignee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("person.person_id"))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Captured from the webhook payload at assignment time (it's already
    # right there) so the daily reminder job can build a real message
    # without needing a GitHub token/API call just to look titles back up.
    # Nullable since rows from before this existed won't have them.
    pr_title: Mapped[str | None] = mapped_column(String, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String, nullable=True)
