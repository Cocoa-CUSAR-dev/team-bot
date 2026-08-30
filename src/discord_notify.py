"""น้องโกโก้ -- posts via a plain Discord incoming webhook (stateless HTTP
POST), not a full bot client. No bot token, no gateway connection, no
Server Members Intent -- and no always-on process requirement, since there's
no persistent connection to keep alive between events.

Trade-off: a webhook can't look anyone up, so mentions need each person's
real numeric Discord ID (Person.discord_id), not their username.
"""

import random
from collections.abc import Sequence

import httpx

from src.config import settings
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
    async with httpx.AsyncClient() as client:
        response = await client.post(
            settings.DISCORD_WEBHOOK_URL,
            json={"username": BOT_USERNAME, "content": content},
            timeout=10,
        )
        response.raise_for_status()


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


# Posted instead of the reminder on a day with zero open reviews -- one
# picked at random, same "never mean" affectionate tone as the other line
# banks. A quiet team deserves a shout-out, not silence.
ALL_CLEAR_LINES = [
    "วันนี้ไม่มี PR ค้างรีวิวเลยจ้า! เก่งกันมากทุกคน 🎉",
    "รีวิวหมดคิวแล้ว ว่างเผื่อไปกินช็อกโกแลตฉลองได้เลย 🍫",
    "กระดานสะอาดจ้า ไม่มีใครติดหนี้รีวิวใครเลยวันนี้ 👏",
    "ทุก PR ผ่านการรีวิวหมดแล้ว ทีมนี้ไวจริง ๆ นะ 😌",
]


def format_daily_reminder(
    open_reviews: Sequence[OpenReview], rng: random.Random | None = None
) -> str:
    """Always returns something to post -- an empty queue is good news, not
    nothing to say, so it gets its own (randomly picked) congratulatory line
    instead of the scheduler silently skipping the day.
    """
    if not open_reviews:
        rng = rng or random.Random()
        return rng.choice(ALL_CLEAR_LINES)

    lines = [
        f"<@{r.discord_id}> — **{r.repo}#{r.pr_number}** — {r.pr_title or '(ไม่มีชื่อ)'} — {r.pr_url or ''}"
        for r in open_reviews
    ]
    return (
        "⏰ เตือนรีวิวประจำวันจ้า ตอนนี้ยังค้างอยู่ทั้งหมดนี้:\n" + "\n".join(lines)
    )


async def announce_daily_reminder(open_reviews: Sequence[OpenReview]) -> None:
    await _post(format_daily_reminder(open_reviews))
