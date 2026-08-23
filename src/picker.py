"""The actual assignment rule -- pure function, no DB/Discord/GitHub calls,
so it's trivially unit-testable. Callers fetch current load and hand it in.

Rules:
  1. Never the PR's own author.
  2. Always draw from whoever currently has the fewest open reviews.
  3. Within a tie, prefer not repeating whoever was *just* assigned
     (globally, not per-repo) -- unless they're the only person left in
     the tie, in which case repeating them is correct, not a bug: with
     more PRs open than people, someone has to double up, and picking
     from the tied-minimum group either way is exactly what keeps work
     "เฉลี่ยงาน" (evenly spread) over time. See 2026-08-20's Discord
     thread -- PR#72/#73 both landing on the same person turned out to
     be two genuine coin flips 14 minutes apart (confirmed against
     assigned_at/resolved_at timestamps), not a bug -- but the rule below
     makes that specific back-to-back feeling less likely going forward
     without changing the forced-repeat behavior anyone already agreed to.
"""

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    person_id: str
    github_username: str
    open_review_count: int


def pick_reviewer(
    *,
    candidates: list[Candidate],
    author_github_username: str,
    last_assigned_github_username: str | None = None,
    rng: random.Random | None = None,
) -> Candidate | None:
    rng = rng or random.Random()

    pool = [c for c in candidates if c.github_username != author_github_username]
    if not pool:
        return None

    min_load = min(c.open_review_count for c in pool)
    least_loaded = [c for c in pool if c.open_review_count == min_load]

    if last_assigned_github_username is not None and len(least_loaded) > 1:
        without_last = [
            c for c in least_loaded if c.github_username != last_assigned_github_username
        ]
        if without_last:  # only drop them if it's not a forced repeat
            least_loaded = without_last

    return rng.choice(least_loaded)
