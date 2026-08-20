"""Run once against a fresh DB: `python -m src.seed`

Reads the roster from roster.local.json (gitignored, never committed) --
real teammates' Discord/GitHub usernames don't belong in tracked source,
even in a private repo. See roster.local.json.example for the shape.
"""

import asyncio
import json
from pathlib import Path

from src.database import Base, async_session_maker, engine
from src.models import Person

ROSTER_PATH = Path(__file__).parent.parent / "roster.local.json"


async def main() -> None:
    if not ROSTER_PATH.exists():
        raise SystemExit(
            f"{ROSTER_PATH} not found -- copy roster.local.json.example to "
            "roster.local.json and fill in the real roster first."
        )
    roster = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as session:
        for entry in roster:
            session.add(
                Person(
                    discord_username=entry["discord_username"],
                    github_username=entry["github_username"],
                    display_name=entry.get("display_name", entry["github_username"]),
                )
            )
        await session.commit()

    print(f"seeded {len(roster)} people")


if __name__ == "__main__":
    asyncio.run(main())
