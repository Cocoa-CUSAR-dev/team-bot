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

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
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


class ClosedPullRequest(Base):
    """PRs we've seen a `closed` event for.

    Exists because the two events can be processed out of order. chatbot#72
    was merged 4 seconds before its own `opened` event finished writing the
    assignment row: resolve_reviews ran first, found nothing to close, and the
    assignment that appeared afterwards could never be resolved by anything --
    it just sat in the daily reminder forever (reported 2026-10-03, "กุตรวจไปแล้ว
    ทำไมขึ้น"). Recording the close lets a late `opened` see it and resolve
    itself immediately.
    """

    __tablename__ = "closed_pr"

    repo: Mapped[str] = mapped_column(String, primary_key=True)
    pr_number: Mapped[int] = mapped_column(primary_key=True)
    closed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PendingAnnouncement(Base):
    """Messages Discord wouldn't take, kept until it will.

    Added 2026-10-03: Discord rate-limits the deployed service at the IP level
    (429, Retry-After 491, while the same webhook answers a laptop instantly),
    so assignments were landing in the DB with nobody getting pinged. The post
    is the only part of this system with no durable record of its own, which
    made it the only part that could silently lose work.

    Stores the rendered text rather than the arguments that produced it: what
    matters is delivering the exact message that was composed at the time, and
    re-deriving it later would mean re-reading state that has since moved on.
    """

    __tablename__ = "pending_announcement"

    announcement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


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
    # Task key parsed out of pr_title (see grouping.py) -- every PR of one
    # task goes to whoever already holds that task, instead of each being
    # load-balanced on its own and then transferred by hand.
    # Nullable and expected to be: plenty of PRs carry no key, and those keep
    # going through the normal picker.
    group_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
