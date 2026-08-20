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
