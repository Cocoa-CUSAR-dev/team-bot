"""Run once against an existing DB:

    python -m src.migrate_closed_pr

Creates the `closed_pr` table. Unlike the group_key migration this needs no
ALTER -- create_all does create MISSING tables, it just never alters existing
ones -- but the deployed service never calls create_all, so something has to.

Safe to re-run; create_all skips tables that already exist.
"""

import asyncio

from src.database import Base, engine
from src.models import ClosedPullRequest  # noqa: F401 -- registers the table


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("closed_pr table in place")


if __name__ == "__main__":
    asyncio.run(main())
