"""Daily check: has anyone changed a repo's env-var *declaration* since
yesterday? Watches each repo's real, git-tracked config -- .env.sample and
render.yaml -- computing a plain SHA-256 over the raw file content and
diffing it against the last-known hash (env_snapshot table).

Deliberately a checksum, not encryption: encryption protects confidentiality
(who can read a value), which isn't the goal here -- these files never hold
real secrets in the first place (.env.sample is a template, render.yaml's
secret entries are `sync: false` placeholders). A hash instead answers "did
the content change at all", which is exactly the question being asked. It
also means this can only ever see what's committed to a public repo -- a
secret's real *value*, changed only inside Render's or GitHub's own
dashboard, never touches git and so is invisible to this check no matter
what cryptographic primitive were used instead.
"""

import hashlib
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import EnvSnapshot

RAW_BASE = "https://raw.githubusercontent.com/Cocoa-CUSAR-dev"

# (repo, ref, path) -- every git-tracked file that declares env var names
# across the project. mobile-app is deliberately absent: it has no env
# file at all, config is Dart --dart-define flags baked in at build time.
WATCHED_FILES = [
    ("chatbot", "dev", ".env.sample"),
    ("database", "dev", ".env.sample"),
    ("mobile-backend", "dev", ".env.sample"),
    ("mobile-backend", "dev", "render.yaml"),
    ("web-app", "dev", ".env.sample"),
    ("web-backend", "dev", ".env.sample"),
    ("team-bot", "main", ".env.sample"),
]


@dataclass(frozen=True)
class DriftEvent:
    repo: str
    path: str
    ref: str
    is_new: (
        bool  # True the first time this file is ever seen (no prior hash to compare)
    )


async def _fetch(
    client: httpx.AsyncClient, repo: str, ref: str, path: str
) -> str | None:
    url = f"{RAW_BASE}/{repo}/{ref}/{path}"
    response = await client.get(url, timeout=10)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def check_env_drift(session: AsyncSession) -> list[DriftEvent]:
    """Fetches every watched file fresh, compares against env_snapshot,
    upserts the new hash either way, and returns what changed.
    """
    events: list[DriftEvent] = []

    async with httpx.AsyncClient() as client:
        for repo, ref, path in WATCHED_FILES:
            content = await _fetch(client, repo, ref, path)
            if content is None:
                continue  # file doesn't exist (yet, or moved) -- nothing to compare
            new_hash = _hash(content)

            existing = await session.get(EnvSnapshot, {"repo": repo, "path": path})
            if existing is None:
                session.add(EnvSnapshot(repo=repo, path=path, sha256=new_hash))
                events.append(DriftEvent(repo=repo, path=path, ref=ref, is_new=True))
            elif existing.sha256 != new_hash:
                existing.sha256 = new_hash
                events.append(DriftEvent(repo=repo, path=path, ref=ref, is_new=False))

    await session.commit()
    return events


async def get_all_snapshots(session: AsyncSession) -> list[EnvSnapshot]:
    result = await session.execute(select(EnvSnapshot))
    return list(result.scalars().all())
