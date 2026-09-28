"""The actual assignment rule -- pure function, no DB/Discord/GitHub calls,
so it's trivially unit-testable. Callers fetch current load and hand it in.

Rules:
  1. Never the PR's own author.
  2. Always draw from whoever has been given the least work RECENTLY --
     assignments inside a rolling window, finished or not (see
     reviews.recent_load_points).

     This used to count only still-open reviews, which punished whoever
     reviewed fastest: finishing dropped your load to zero and the very next
     PR came straight back to you, while someone sitting on six untouched PRs
     looked "busy" and was left alone. Reported 2026-09-28 by the person with
     30 finished reviews and 2 open, who was still first in line for the next
     one. Counting work *dealt out* rather than work *pending* removes the
     incentive to sit on a queue.
  3. Ties on recent work break on who's carrying the bigger open backlog, so
     the fast reviewer wins a tie against someone equally-dealt but stuck.
  4. Within a tie, prefer not repeating whoever was *just* assigned
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
    # Both are points, not PR counts -- follow-on PRs of one task are
    # half-price (see reviews.group_load_points). Floats tie exactly here:
    # they're sums of 0.5s, not measurements.
    #
    # recent_load decides; open_load only breaks ties between people who were
    # dealt the same amount, favouring whoever has less still sitting there.
    recent_load: float
    open_load: float = 0.0


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

    def load_key(c: Candidate) -> tuple[float, float]:
        return (c.recent_load, c.open_load)

    min_load = min(load_key(c) for c in pool)
    least_loaded = [c for c in pool if load_key(c) == min_load]

    if last_assigned_github_username is not None and len(least_loaded) > 1:
        without_last = [
            c for c in least_loaded if c.github_username != last_assigned_github_username
        ]
        if without_last:  # only drop them if it's not a forced repeat
            least_loaded = without_last

    return rng.choice(least_loaded)
