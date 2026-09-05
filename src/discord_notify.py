"""น้องโกโก้ -- posts via a plain Discord incoming webhook (stateless HTTP
POST), not a full bot client. No bot token, no gateway connection, no
Server Members Intent -- and no always-on process requirement, since there's
no persistent connection to keep alive between events.

Trade-off: a webhook can't look anyone up, so mentions need each person's
real numeric Discord ID (Person.discord_id), not their username.
"""

import asyncio
import random
from collections.abc import Sequence

import httpx

from src.config import settings
from src.env_drift import DriftEvent
from src.reviews import OpenReview

BOT_USERNAME = "🍫 น้องโกโก้"

# One picked at random per assignment -- กวนๆ, never mean, matches the same
# affectionate-teasing tone as the Sprint Wrapped page.
TEASING_LINES = [
    "หนีไม่พ้นแล้วจ้า 🏃💨",
    "ระบบสุ่มชี้มาที่คุณแหละ อย่าถามน้องโกโก้ว่าทำไม บอทก็แค่ทำตามหน้าที่",
    "ยินดีด้วยนะ ได้รับเกียรติ (?) ให้ตรวจ PR นี้ต่อไป",
    "กรรมเก่าตามทัน รีวิวใหม่มาแล้วจ้า",
    "สุ่มไม่โกง สัญญาด้วยเมล็ดโกโก้",
    "จับสลากได้คุณพอดีเป๊ะ เก่งจัง (ไม่ใช่คำชม)",
]

# Praise on PR merge -- one picked at random, except Boom (Rirhcceez) gets
# his own line by direct team request (2026-08-20 Discord thread).
BOOM_GITHUB_USERNAME = "Rirhcceez"
BOOM_PRAISE_LINE = "很棒呀～～ 哥哥。"

PRAISE_LINES = [
    "งานดีมาก รีวิวไวด้วย 👏",
    "เก่งอ่ะ ตรวจละเอียดจริง",
    "ผ่านฉลุย ขอบคุณที่ช่วยดูให้นะ",
    "น้องโกโก้ปลื้มใจ รีวิวเสร็จไวปึ้ก",
    "MVP ประจำรอบนี้ 🏆",
]


def choose_praise_line(reviewer_github_username: str, rng: random.Random | None = None) -> str:
    if reviewer_github_username == BOOM_GITHUB_USERNAME:
        return BOOM_PRAISE_LINE
    rng = rng or random.Random()
    return rng.choice(PRAISE_LINES)


async def _post(content: str) -> None:
    # Discord rate-limits a single incoming webhook fairly aggressively, and
    # two PRs opened moments apart (e.g. a migration + the code that reads
    # it) both hit this within the same request-handling window often
    # enough to trip it for real -- confirmed 2026-09-01 on database#32 /
    # chatbot#46. A 429 carries exactly how long to wait, so one retry
    # after that (rather than giving up, or blindly retrying forever) is
    # enough to ride out a same-second double-post.
    async with httpx.AsyncClient() as client:
        for attempt in range(2):
            response = await client.post(
                settings.DISCORD_WEBHOOK_URL,
                json={"username": BOT_USERNAME, "content": content},
                timeout=10,
            )
            if response.status_code == 429 and attempt == 0:
                retry_after = _rate_limit_wait_seconds(response)
                await asyncio.sleep(retry_after)
                continue
            response.raise_for_status()
            return


def _rate_limit_wait_seconds(response: httpx.Response) -> float:
    """Discord sends the wait time both as a `Retry-After` header (seconds)
    and in the JSON body's `retry_after` field -- prefer the header since it
    doesn't require the body to actually be valid JSON, fall back to the
    body, and fall back to a conservative 1s if somehow neither is present.
    """
    header_value = response.headers.get("Retry-After")
    if header_value is not None:
        try:
            return float(header_value)
        except ValueError:
            pass
    try:
        return float(response.json().get("retry_after", 1))
    except (ValueError, TypeError, AttributeError):
        # ValueError covers both invalid JSON (json.JSONDecodeError is a
        # subclass) and a non-numeric retry_after; AttributeError covers a
        # valid-but-non-object JSON body (e.g. a bare array) with no .get().
        return 1.0


async def announce_assignment(*, repo: str, pr_number: int, pr_title: str, pr_url: str,
                               reviewer_discord_id: str, author_github_username: str) -> None:
    teasing = random.choice(TEASING_LINES)
    await _post(
        f"<@{reviewer_discord_id}> ถึงคิวรีวิวแล้วจ้า! {teasing}\n"
        f"**{repo}#{pr_number}** — {pr_title}\n"
        f"เปิดโดย `{author_github_username}` — {pr_url}"
    )


async def announce_review_done(*, repo: str, pr_number: int, pr_title: str, pr_url: str,
                                reviewer_display_name: str, reviewer_github_username: str,
                                author_discord_id: str | None, author_github_username: str) -> None:
    """Posted on PR merge -- pings the AUTHOR (not the reviewer) to let them
    know their PR made it through review, and praises whoever reviewed it.
    author_discord_id is None when the author isn't one of the 4 tracked
    people (falls back to their GitHub username, not a broken mention).
    """
    praise = choose_praise_line(reviewer_github_username)
    who = f"<@{author_discord_id}>" if author_discord_id else f"`{author_github_username}`"
    await _post(
        f"{who} รีวิวเสร็จแล้วจ้า! {praise}\n"
        f"**{repo}#{pr_number}** — {pr_title}\n"
        f"ตรวจโดย {reviewer_display_name} — {pr_url}"
    )


async def announce_no_reviewer_available(*, repo: str, pr_number: int, pr_title: str) -> None:
    """Only fires if literally everyone linked is the PR author -- shouldn't
    happen with a real 4-person roster on someone else's repo, but silently
    dropping the PR would be worse than saying so.
    """
    await _post(
        f"**{repo}#{pr_number}** — {pr_title}\n"
        f"⚠️ หาคนรีวิวให้ไม่ได้เลย (ทุกคนในทีมเป็นคนเปิด PR นี้พร้อมกันได้ไงเนี่ย 🤔)"
    )


def format_daily_reminder(open_reviews: Sequence[OpenReview]) -> str | None:
    """None means "nothing to post" -- the scheduler skips sending anything
    rather than spamming an empty "all clear" message every single evening.
    """
    if not open_reviews:
        return None

    lines = [
        f"<@{r.discord_id}> — **{r.repo}#{r.pr_number}** — {r.pr_title or '(ไม่มีชื่อ)'} — {r.pr_url or ''}"
        for r in open_reviews
    ]
    return (
        "⏰ เตือนรีวิวประจำวันจ้า ตอนนี้ยังค้างอยู่ทั้งหมดนี้:\n" + "\n".join(lines)
    )


async def announce_daily_reminder(open_reviews: Sequence[OpenReview]) -> None:
    content = format_daily_reminder(open_reviews)
    if content is not None:
        await _post(content)


async def announce_env_drift(events: Sequence[DriftEvent]) -> None:
    """Posted only when something actually changed -- unlike an empty review
    queue, an unchanged env file is just the normal daily state, not a
    special occasion, so staying quiet on a no-drift day is the right call
    (the opposite tradeoff from announce_daily_reminder above).

    `is_new` events (a watched file's very first check, nothing to diff
    against yet) are silently skipped too -- day one of watching a file
    isn't a change, it's a baseline.
    """
    changed = [e for e in events if not e.is_new]
    if not changed:
        return

    lines = [
        f"**{e.repo}/{e.path}** (`{e.ref}`) — "
        f"https://github.com/Cocoa-CUSAR-dev/{e.repo}/commits/{e.ref}/{e.path}"
        for e in changed
    ]
    await _post(
        "🔎 เอ๊ะ มีคนแก้ env var list ตั้งแต่เช็กครั้งก่อนนะ ไปดูหน่อยว่าใครแก้อะไร:\n"
        + "\n".join(lines)
    )
