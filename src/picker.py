"""The actual assignment rule -- pure function, no DB/Discord/GitHub calls,
so it's trivially unit-testable. Callers fetch current load and hand it in.

Two rules, straight from spec:
  1. Never the PR's own author.
  2. Always draw from whoever currently has the fewest open reviews --
     which is exactly what makes "don't repeat someone unless everyone
     else is tied" true, without needing a separate rule for it.
"""

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    person_id: str
    github_username: str
    open_review_count: int


def pick_reviewer(
    *, candidates: list[Candidate], author_github_username: str, rng: random.Random | None = None
) -> Candidate | None:
    rng = rng or random.Random()

    pool = [c for c in candidates if c.github_username != author_github_username]
    if not pool:
        return None

    min_load = min(c.open_review_count for c in pool)
    least_loaded = [c for c in pool if c.open_review_count == min_load]

    return rng.choice(least_loaded)
