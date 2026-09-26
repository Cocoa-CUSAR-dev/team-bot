from datetime import UTC, datetime, timedelta

from src.discord_notify import format_my_reviews
from src.reviews import OpenReview

DISCORD_ID = "656802605267157004"


def _review(**overrides) -> OpenReview:
    defaults = {
        "repo": "Cocoa-CUSAR-dev/mobile-backend",
        "pr_number": 1,
        "pr_title": "fix: something",
        "pr_url": "https://github.com/x/y/pull/1",
        "discord_id": DISCORD_ID,
        "assigned_at": datetime.now(UTC),
    }
    return OpenReview(**{**defaults, **overrides})


def test_mentions_the_asker_so_it_reads_right_in_channel() -> None:
    text = format_my_reviews([_review()], discord_id=DISCORD_ID)

    assert f"<@{DISCORD_ID}>" in text


def test_lists_each_open_review() -> None:
    reviews = [_review(pr_number=1), _review(pr_number=2)]

    text = format_my_reviews(reviews, discord_id=DISCORD_ID)

    assert "#1" in text
    assert "#2" in text
    assert "2 รายการ" in text


def test_empty_list_says_so_rather_than_printing_nothing() -> None:
    text = format_my_reviews([], discord_id=DISCORD_ID)

    assert f"<@{DISCORD_ID}>" in text
    assert "ไม่มี PR ค้างรีวิว" in text


def test_not_in_roster_is_distinct_from_having_zero_reviews() -> None:
    """Both return an empty list, but they mean different things -- saying
    "you have no reviews" to someone who was never seeded is just wrong.
    """
    text = format_my_reviews([], discord_id=DISCORD_ID, in_roster=False)

    assert "roster" in text
    assert "ไม่มี PR ค้างรีวิว" not in text


def test_overdue_item_gets_the_same_fire_marker_as_the_daily_reminder() -> None:
    now = datetime(2026, 9, 26, tzinfo=UTC)
    fresh = _review(pr_number=1, assigned_at=now - timedelta(hours=2))
    overdue = _review(pr_number=2, assigned_at=now - timedelta(days=4))

    text = format_my_reviews([fresh, overdue], discord_id=DISCORD_ID, now=now)

    fresh_at = text.index("#1")
    overdue_at = text.index("#2")
    # The flame belongs to #2's line only, not #1's.
    assert "🔥" not in text[:fresh_at]
    assert "🔥" in text[fresh_at:overdue_at]


def test_missing_title_does_not_print_none() -> None:
    text = format_my_reviews(
        [_review(pr_title=None, pr_url=None)], discord_id=DISCORD_ID
    )

    assert "None" not in text
