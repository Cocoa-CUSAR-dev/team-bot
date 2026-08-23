import random

from src.picker import Candidate, pick_reviewer


def _candidates(**loads: int) -> list[Candidate]:
    return [
        Candidate(person_id=name, github_username=name, open_review_count=load)
        for name, load in loads.items()
    ]


def test_never_picks_the_author_even_if_least_loaded() -> None:
    candidates = _candidates(alice=0, bob=3, carol=3)

    chosen = pick_reviewer(candidates=candidates, author_github_username="alice")

    assert chosen is not None
    assert chosen.github_username != "alice"


def test_picks_from_the_least_loaded_group_only() -> None:
    candidates = _candidates(alice=5, bob=1, carol=1, dave=4)

    for seed in range(20):
        chosen = pick_reviewer(
            candidates=candidates,
            author_github_username="alice",
            rng=random.Random(seed),
        )
        assert chosen.github_username in {"bob", "carol"}


def test_returns_none_when_everyone_is_the_author() -> None:
    candidates = _candidates(alice=0)

    chosen = pick_reviewer(candidates=candidates, author_github_username="alice")

    assert chosen is None


def test_ties_actually_vary_across_seeds() -> None:
    """Not just "picks a valid person" -- confirms the randomness is real,
    not accidentally deterministic (e.g. always picking candidates[0]).
    """
    candidates = _candidates(bob=1, carol=1, dave=1)

    picks = {
        pick_reviewer(
            candidates=candidates, author_github_username="alice", rng=random.Random(seed)
        ).github_username
        for seed in range(30)
    }

    assert len(picks) > 1


def test_avoids_repeating_the_last_assignee_when_others_are_tied() -> None:
    """The actual 2026-08-20 report: same person picked twice in a row felt
    wrong even though it was a legitimate coin flip (confirmed against real
    assigned_at/resolved_at timestamps -- not a stale-load bug). This is the
    fix: don't hand a genuine 3-way tie back to whoever *just* got it.
    """
    candidates = _candidates(bob=0, carol=0, dave=0)

    for seed in range(30):
        chosen = pick_reviewer(
            candidates=candidates,
            author_github_username="alice",
            last_assigned_github_username="bob",
            rng=random.Random(seed),
        )
        assert chosen.github_username != "bob"


def test_still_repeats_the_last_assignee_when_forced() -> None:
    """More open PRs than people -- everyone else already has one, so the
    tied-minimum group is just the last-assigned person alone. Repeating
    them here is correct (this is the "เฉลี่ยงาน" case the team explicitly
    signed off on), not something the tie-break should block.
    """
    candidates = _candidates(bob=1, carol=2, dave=2)  # bob is the sole least-loaded

    chosen = pick_reviewer(
        candidates=candidates,
        author_github_username="alice",
        last_assigned_github_username="bob",
    )

    assert chosen.github_username == "bob"


def test_last_assignee_outside_the_tie_does_not_affect_the_pick() -> None:
    """last_assigned_github_username only matters if that person is actually
    IN the tied-minimum group -- someone who already has more load than the
    tie isn't a candidate anyway, so there's nothing to exclude.
    """
    candidates = _candidates(bob=5, carol=0, dave=0)

    for seed in range(20):
        chosen = pick_reviewer(
            candidates=candidates,
            author_github_username="alice",
            last_assigned_github_username="bob",
            rng=random.Random(seed),
        )
        assert chosen.github_username in {"carol", "dave"}
