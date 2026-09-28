"""The wording is the point of this feature as much as the routing is: a PR
handed to someone because they already hold the task looks, from the channel,
exactly like the bot ignoring load -- especially when the PRs land days apart.
"""

from datetime import UTC, datetime, timedelta

from src.discord_notify import describe_group_follow_on
from src.reviews import GroupPredecessor

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def _predecessor(**overrides) -> GroupPredecessor:
    defaults = {
        "repo": "Cocoa-CUSAR-dev/web-backend",
        "pr_number": 48,
        "pr_title": "feat(sentry): add error tracking — web-backend (X-2d)",
        "pr_url": "https://github.com/Cocoa-CUSAR-dev/web-backend/pull/48",
        "assigned_at": NOW,
    }
    return GroupPredecessor(**{**defaults, **overrides})


def test_names_the_task_and_the_earlier_pr() -> None:
    text = describe_group_follow_on(
        group_key="x2d", predecessor=_predecessor(), now=NOW
    )

    assert "x2d" in text
    assert "web-backend#48" in text


def test_says_outright_that_it_was_not_random() -> None:
    text = describe_group_follow_on(
        group_key="x2d", predecessor=_predecessor(), now=NOW
    )

    assert "ไม่ได้สุ่ม" in text


def test_days_apart_is_spelled_out_rather_than_implied() -> None:
    """The case this exists for -- PRs of one task arriving 3 days apart."""
    text = describe_group_follow_on(
        group_key="x2d",
        predecessor=_predecessor(assigned_at=NOW - timedelta(days=3)),
        now=NOW,
    )

    assert "3 วันก่อน" in text


def test_same_batch_reads_as_just_now_not_zero_days() -> None:
    text = describe_group_follow_on(
        group_key="x2d",
        predecessor=_predecessor(assigned_at=NOW - timedelta(minutes=2)),
        now=NOW,
    )

    assert "0 วัน" not in text


def test_missing_predecessor_url_does_not_print_none() -> None:
    """Rows from before pr_url existed have None there."""
    text = describe_group_follow_on(
        group_key="x2d", predecessor=_predecessor(pr_url=None), now=NOW
    )

    assert "None" not in text
