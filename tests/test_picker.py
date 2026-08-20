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
