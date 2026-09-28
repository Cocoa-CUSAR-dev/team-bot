"""Half-price weighting for a task's follow-on PRs.

The two numbers to keep an eye on are the extremes this deliberately avoids:
5 PRs of one task must be worth neither 5 points (holder gets ignored for
days, then catches everything at once when the batch merges) nor 1 point
(picker can't tell them apart from someone holding a single PR).
"""

import pytest

from src.picker import Candidate, pick_reviewer
from src.reviews import group_load_points


@pytest.mark.parametrize(
    ("pr_count", "expected"),
    [(1, 1.0), (2, 1.5), (3, 2.0), (5, 3.0), (10, 5.5)],
)
def test_first_pr_full_price_rest_half(pr_count: int, expected: float) -> None:
    assert group_load_points(pr_count) == expected


def test_a_five_pr_task_is_neither_one_nor_five() -> None:
    points = group_load_points(5)
    assert 1.0 < points < 5.0


def test_no_open_prs_is_zero_not_one() -> None:
    """Guards the `1.0 +` baseline against being charged to someone with an
    empty queue, which would make every load look inflated by one.
    """
    assert group_load_points(0) == 0.0


def test_unkeyed_prs_still_cost_one_each() -> None:
    """Each is its own group of one, so three separate PRs cost 3.0 -- twice
    what three PRs of a single task cost.
    """
    separate = sum(group_load_points(1) for _ in range(3))
    one_task = group_load_points(3)

    assert separate == 3.0
    assert one_task == 2.0


def test_picker_prefers_the_lighter_load_across_fractional_points() -> None:
    """A holder of a 3-PR task (2.0) must still be passed over for someone
    holding a single PR (1.0) -- the half-price rule discounts, it doesn't
    make a group free.
    """
    group_holder = Candidate(person_id="a", github_username="a", open_review_count=2.0)
    lighter = Candidate(person_id="b", github_username="b", open_review_count=1.0)

    chosen = pick_reviewer(
        candidates=[group_holder, lighter], author_github_username="someone-else"
    )

    assert chosen is lighter


def test_group_holder_is_still_reachable_once_they_are_the_lightest() -> None:
    """The flip side: discounting means they come back into rotation sooner
    than a linear count would allow.
    """
    group_holder = Candidate(person_id="a", github_username="a", open_review_count=2.0)
    busier = Candidate(person_id="b", github_username="b", open_review_count=3.0)

    chosen = pick_reviewer(
        candidates=[group_holder, busier], author_github_username="someone-else"
    )

    assert chosen is group_holder
