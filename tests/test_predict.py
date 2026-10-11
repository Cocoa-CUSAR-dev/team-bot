"""/predict has one job: say what the picker would really do.

A prediction that disagrees with the assignment is worse than no prediction
at all, so the tests that matter here are the ones tying it to picker.shortlist
rather than to a nice-looking message.
"""

import random

from src.discord_notify import format_prediction
from src.picker import Candidate, pick_reviewer, shortlist
from src.predict import Outcome, Prediction, Standing


def _standing(name: str, recent: float, open_load: float = 0.0) -> Standing:
    return Standing(
        display_name=name,
        github_username=name,
        discord_id=f"id-{name}",
        recent_load=recent,
        open_load=open_load,
    )


def _candidate(s: Standing) -> Candidate:
    return Candidate(
        person_id=s.github_username,
        github_username=s.github_username,
        recent_load=s.recent_load,
        open_load=s.open_load,
    )


def test_the_shortlist_is_exactly_what_the_picker_draws_from() -> None:
    """The guarantee the whole command rests on. If pick_reviewer could ever
    return someone outside the shortlist, /predict would be lying.
    """
    people = [_standing("a", 1.0), _standing("b", 1.0), _standing("c", 5.0)]
    candidates = [_candidate(s) for s in people]

    finalists = {
        c.github_username
        for c in shortlist(candidates=candidates, author_github_username="c")
    }
    picked = {
        pick_reviewer(
            candidates=candidates,
            author_github_username="c",
            rng=random.Random(seed),
        ).github_username
        for seed in range(50)
    }

    assert picked <= finalists
    assert picked == finalists, "every finalist should be reachable"


def test_an_author_never_appears_in_their_own_shortlist() -> None:
    people = [_standing("a", 0.0), _standing("b", 9.0)]
    candidates = [_candidate(s) for s in people]

    finalists = shortlist(candidates=candidates, author_github_username="a")

    assert [c.github_username for c in finalists] == ["b"]


def test_a_lone_author_has_nobody_to_review_their_pr() -> None:
    candidates = [_candidate(_standing("a", 0.0))]

    assert shortlist(candidates=candidates, author_github_username="a") == []


# --- the message -----------------------------------------------------------


def _prediction() -> Prediction:
    a, b, c = _standing("a", 1.0), _standing("b", 1.0, 2.0), _standing("c", 5.0)
    return Prediction(
        standings=[a, b, c],
        outcomes=[
            Outcome(author=a, finalists=[b]),
            Outcome(author=b, finalists=[a]),
            Outcome(author=c, finalists=[a, b]),
        ],
        last_assigned="c",
        window_days=14,
    )


def test_it_never_pings_anyone() -> None:
    """It names the whole roster and people will run it out of curiosity --
    mentions would notify everyone for a question nobody asked.
    """
    text = format_prediction(_prediction())

    assert "<@" not in text


def test_every_member_and_their_points_are_shown() -> None:
    text = format_prediction(_prediction())

    for name in ("a", "b", "c"):
        assert name in text
    assert "5 แต้ม" in text


def test_a_two_way_tie_is_reported_as_a_coin_flip() -> None:
    text = format_prediction(_prediction())

    assert "50%" in text


def test_a_certain_outcome_is_not_dressed_up_as_a_probability() -> None:
    text = format_prediction(_prediction())

    assert "100%" not in text
    assert "แน่นอน" in text


def test_it_says_who_went_last_since_that_changes_the_tie_break() -> None:
    text = format_prediction(_prediction())

    assert "c" in text
    assert "เสมอ" in text


def test_whole_points_print_without_a_trailing_zero() -> None:
    """`:g` keeps 1.5 as 1.5 but shows 5 rather than 5.0 -- half-points are
    real here, so they have to survive, without littering every other line.
    """
    text = format_prediction(_prediction())

    assert "5.0 แต้ม" not in text
