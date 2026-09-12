import random
from datetime import UTC, datetime, timedelta

from src.discord_notify import DRAGON_LINES, format_daily_reminder
from src.reviews import OpenReview


def _review(**overrides) -> OpenReview:
    defaults = {
        "repo": "Cocoa-CUSAR-dev/mobile-backend",
        "pr_number": 1,
        "pr_title": "fix: something",
        "pr_url": "https://github.com/x/y/pull/1",
        "discord_id": "656802605267157004",
        "assigned_at": datetime.now(UTC),
    }
    return OpenReview(**{**defaults, **overrides})


def test_returns_none_when_nothing_is_open() -> None:
    assert format_daily_reminder([]) is None


def test_lists_every_open_review_with_a_real_mention() -> None:
    reviews = [
        _review(pr_number=1, discord_id="111"),
        _review(pr_number=2, discord_id="222"),
    ]

    text = format_daily_reminder(reviews)

    assert text is not None
    assert "<@111>" in text
    assert "<@222>" in text
    assert "#1" in text
    assert "#2" in text


def test_missing_title_falls_back_instead_of_printing_none() -> None:
    """Rows from before pr_title/pr_url existed are NULL in the DB --
    must not literally print "None" in the Discord message.
    """
    text = format_daily_reminder([_review(pr_title=None, pr_url=None)])

    assert text is not None
    assert "None" not in text


def test_fresh_review_gets_no_dragon() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    review = _review(assigned_at=now - timedelta(days=1))

    text = format_daily_reminder([review], now=now)

    assert text is not None
    assert not any(line in text for line in DRAGON_LINES)


def test_review_open_more_than_two_days_gets_a_dragon_line() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    review = _review(assigned_at=now - timedelta(days=3))

    text = format_daily_reminder([review], now=now, rng=random.Random(0))

    assert text is not None
    assert any(line in text for line in DRAGON_LINES)
    assert "ค้างมา 3 วันแล้ว" in text


def test_exactly_two_days_is_not_yet_overdue() -> None:
    """"more than 2 days" is strict -- exactly on the boundary doesn't
    trigger the dragon yet, only crossing past it does.
    """
    now = datetime(2026, 9, 12, tzinfo=UTC)
    review = _review(assigned_at=now - timedelta(days=2))

    text = format_daily_reminder([review], now=now)

    assert text is not None
    assert not any(line in text for line in DRAGON_LINES)


def test_mix_of_fresh_and_overdue_only_flags_the_overdue_one() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    fresh = _review(pr_number=1, assigned_at=now - timedelta(hours=3))
    overdue = _review(pr_number=2, assigned_at=now - timedelta(days=5))

    text = format_daily_reminder([fresh, overdue], now=now, rng=random.Random(0))

    assert text is not None
    fresh_line_start = text.index("#1")
    overdue_line_start = text.index("#2")
    # The dragon line for #2 is prepended right before its own mention/PR
    # line, and shouldn't bleed backward onto #1's line.
    assert not any(line in text[:fresh_line_start] for line in DRAGON_LINES)
    assert any(line in text[:overdue_line_start] for line in DRAGON_LINES)
