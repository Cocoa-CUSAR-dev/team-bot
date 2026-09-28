"""Run once against an existing DB:

    python -m src.migrate_group_key          # dry run, prints what it'd do
    python -m src.migrate_group_key --apply

Adds review_assignment.group_key and backfills it from the PR titles already
stored on every row.

There's no migration framework here -- seed.py just runs create_all, which
creates missing TABLES but never alters an existing one, so a new column on a
live DB needs this. Written to be safely re-runnable (IF NOT EXISTS, and the
backfill only touches rows still NULL).

The backfill is the part that matters day one: without it, every PR of a task
that's already in flight looks like a brand-new key, and the first few PRs
after deploy would scatter exactly as before.
"""

import asyncio
import sys

from sqlalchemy import select, text

from src.database import async_session_maker, engine
from src.grouping import extract_group_key
from src.models import ReviewAssignment

DDL = [
    "ALTER TABLE review_assignment ADD COLUMN IF NOT EXISTS group_key VARCHAR",
    (
        "CREATE INDEX IF NOT EXISTS ix_review_assignment_group_key "
        "ON review_assignment (group_key)"
    ),
]


async def main(apply: bool) -> None:
    if apply:
        async with engine.begin() as conn:
            for statement in DDL:
                await conn.execute(text(statement))
        print("schema: column + index in place")
    else:
        print("schema: would run ->")
        for statement in DDL:
            print(f"  {statement}")

    async with async_session_maker() as session:
        if apply:
            rows = (
                (
                    await session.execute(
                        select(ReviewAssignment).where(ReviewAssignment.group_key.is_(None))
                    )
                )
                .scalars()
                .all()
            )
        else:
            # Name the columns explicitly: a whole-entity select would ask for
            # group_key, which on a dry run doesn't exist yet.
            rows = (
                await session.execute(
                    select(
                        ReviewAssignment.repo,
                        ReviewAssignment.pr_number,
                        ReviewAssignment.pr_title,
                    )
                )
            ).all()

        filled = 0
        for row in rows:
            title = row.pr_title
            key = extract_group_key(title)
            if key is None:
                continue
            filled += 1
            print(f"  {row.repo}#{row.pr_number} -> {key}")
            if apply:
                row.group_key = key

        if apply:
            await session.commit()
            print(f"backfilled {filled} of {len(rows)} rows")
        else:
            print(f"backfill: would set {filled} of {len(rows)} rows (re-run with --apply)")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
