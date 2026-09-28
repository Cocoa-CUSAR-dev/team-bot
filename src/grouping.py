"""Pulls the task key out of a PR title, so PRs belonging to one task can be
routed to one reviewer (see reviews.assign_reviewer).

Nobody added this convention for the bot -- the team was already writing keys
by hand before the bot could read them, in two different styles:

    feat(sentry): add error tracking -- web-app (X-2d)
    feat(x6d): gate production deploy behind a GitHub Environment
    test(US2-5): autofill pipeline parity e2e (#106)

so both are accepted rather than picking a winner and silently breaking half
the existing titles.

A key must contain BOTH a letter and a digit. That one rule is what keeps the
two things that look identical to a regex apart:

    (X-2d)        -> key
    (#106)        -> not a key, it's a PR reference
    (106)         -> not a key
    feat(logging) -> not a key, it's a conventional-commit scope

Normalisation lowercases and drops separators, so `X-2d` and `x2d` are the
same group. That does mean `US2-5` and `US25` would collide -- acceptable for
a 4-person team with a handful of live tasks, and far less annoying than two
spellings of one key silently splitting a group in half.
"""

import re

# Either a parenthesised key -- (X-2d) -- or a conventional-commit scope --
# feat(x6d): -- both of which put the candidate inside the same brackets.
_BRACKETED = re.compile(r"\(([^()]{1,20})\)")

_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT = re.compile(r"\d")
# Letters, digits, hyphens and underscores only. A key with a space or a `#`
# in it is prose or a PR reference, not a key.
_KEY_SHAPED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def normalise_group_key(raw: str) -> str:
    return re.sub(r"[^a-z0-9]", "", raw.lower())


def extract_group_key(pr_title: str | None) -> str | None:
    """The first key-shaped bracketed token, normalised -- or None when the
    title carries no key at all, which is the common case and must keep
    working (the caller falls back to the normal load-balancing picker).
    """
    if not pr_title:
        return None

    for candidate in _BRACKETED.findall(pr_title):
        candidate = candidate.strip()
        if not _KEY_SHAPED.match(candidate):
            continue
        if not (_HAS_LETTER.search(candidate) and _HAS_DIGIT.search(candidate)):
            continue
        return normalise_group_key(candidate)

    return None
