"""The 2026-09-28 report: counting only still-open reviews meant finishing
your queue made you the next target, while sitting on an untouched pile kept
you off the hook. Reported by the person with 30 finished / 2 open who was
still first in line.
"""

from src.picker import Candidate, pick_reviewer


def test_finishing_everything_does_not_make_you_the_next_target() -> None:
    """The exact shape of the complaint: `fast` has been dealt 5 points of
    work and cleared all of it; `slow` was dealt 2 and is still sitting on
    them. The old open-only rule scored fast at 0 and slow at 2, so fast got
    the next PR -- and the one after that. Dealt-work has to decide.
    """
    fast = Candidate(
        person_id="fast", github_username="fast", recent_load=5.0, open_load=0.0
    )
    slow = Candidate(
        person_id="slow", github_username="slow", recent_load=2.0, open_load=2.0
    )

    chosen = pick_reviewer(candidates=[fast, slow], author_github_username="author")

    assert chosen is slow


def test_equal_dealt_work_goes_to_whoever_has_room() -> None:
    """Deliberately NOT the same as the test above. Once two people have been
    dealt the same amount, speed stops being the question and capacity starts:
    the one with an empty queue can actually look at it today. That isn't
    punishing them -- the work they already finished is still counted against
    them in recent_load, so they stop winning these ties as soon as the totals
    diverge again.
    """
    cleared = Candidate(person_id="a", github_username="a", recent_load=4.0, open_load=0.0)
    piled_up = Candidate(person_id="b", github_username="b", recent_load=4.0, open_load=4.0)

    chosen = pick_reviewer(
        candidates=[cleared, piled_up], author_github_username="author"
    )

    assert chosen is cleared


def test_a_big_backlog_no_longer_shields_you_from_new_work() -> None:
    """The other half of the same bug: `hoarder` has plenty open but was dealt
    little recently, so they're the right choice -- an open queue is not a
    reason to be skipped.
    """
    hoarder = Candidate(
        person_id="hoarder", github_username="hoarder", recent_load=1.0, open_load=5.0
    )
    busy = Candidate(
        person_id="busy", github_username="busy", recent_load=5.0, open_load=1.0
    )

    chosen = pick_reviewer(candidates=[hoarder, busy], author_github_username="author")

    assert chosen is hoarder


def test_open_backlog_only_breaks_a_tie() -> None:
    """Equal recent work -- then, and only then, prefer whoever has less still
    sitting unreviewed.
    """
    clear = Candidate(person_id="a", github_username="a", recent_load=2.0, open_load=0.0)
    stuck = Candidate(person_id="b", github_username="b", recent_load=2.0, open_load=3.0)

    chosen = pick_reviewer(candidates=[clear, stuck], author_github_username="author")

    assert chosen is clear


def test_recent_load_outranks_backlog_rather_than_being_added_to_it() -> None:
    """If the two were summed, `light` would score 1+9=10 and `heavy` 6+0=6,
    and heavy would win despite having been dealt six times the work. Recent
    work has to decide outright.
    """
    light = Candidate(person_id="a", github_username="a", recent_load=1.0, open_load=9.0)
    heavy = Candidate(person_id="b", github_username="b", recent_load=6.0, open_load=0.0)

    chosen = pick_reviewer(candidates=[light, heavy], author_github_username="author")

    assert chosen is light
