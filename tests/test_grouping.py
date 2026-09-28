"""The false-POSITIVE cases matter more than the true ones: a wrong key sends
an unrelated PR to whoever happens to hold that group, which is worse than
the status quo of just load-balancing it.
"""

import pytest

from src.grouping import extract_group_key


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("feat(sentry): add error tracking — web-app (X-2d)", "x2d"),
        ("feat(logging): structured JSON logs — chatbot (X-2c)", "x2c"),
        ("feat(x6d): gate production deploy behind a GitHub Environment", "x6d"),
        ("test(US2-5): autofill pipeline parity e2e (#106)", "us25"),
    ],
)
def test_reads_both_title_styles_the_team_actually_uses(title: str, expected: str) -> None:
    assert extract_group_key(title) == expected


def test_case_and_hyphens_do_not_split_a_group() -> None:
    assert extract_group_key("thing (X-2D)") == extract_group_key("thing (x2d)")


@pytest.mark.parametrize(
    "title",
    [
        "Feat web UI notification",
        "feat(logging): structured JSON logs",  # scope, no digit
        "test: autofill pipeline parity e2e (#106)",  # PR reference
        "chore: bump deps (106)",  # bare number
        "fix: handle empty response (see issue 12)",  # prose
        "fix: something ()",
    ],
)
def test_titles_without_a_key_return_none(title: str) -> None:
    assert extract_group_key(title) is None


def test_no_title_at_all_is_not_an_error() -> None:
    """pr_title is nullable on old rows -- this must not raise."""
    assert extract_group_key(None) is None
    assert extract_group_key("") is None


def test_conventional_commit_scope_wins_over_a_later_pr_reference() -> None:
    """Both are bracketed; the scope comes first and is the real key."""
    assert extract_group_key("feat(x6d): tidy up (#204)") == "x6d"
