from src.discord_notify import format_daily_reminder
from src.reviews import OpenReview


def _review(**overrides) -> OpenReview:
    defaults = dict(repo="Cocoa-CUSAR-dev/mobile-backend", pr_number=1,
                     pr_title="fix: something", pr_url="https://github.com/x/y/pull/1",
                     discord_id="656802605267157004")
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
