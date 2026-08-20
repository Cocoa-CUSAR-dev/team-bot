"""น้องโกโก้ -- posts via a plain Discord incoming webhook (stateless HTTP
POST), not a full bot client. No bot token, no gateway connection, no
Server Members Intent -- and no always-on process requirement, since there's
no persistent connection to keep alive between events.

Trade-off: a webhook can't look anyone up, so mentions need each person's
real numeric Discord ID (Person.discord_id), not their username.
"""

import random

import httpx

from src.config import settings

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


async def announce_no_reviewer_available(*, repo: str, pr_number: int, pr_title: str) -> None:
    """Only fires if literally everyone linked is the PR author -- shouldn't
    happen with a real 4-person roster on someone else's repo, but silently
    dropping the PR would be worse than saying so.
    """
    await _post(
        f"**{repo}#{pr_number}** — {pr_title}\n"
        f"⚠️ หาคนรีวิวให้ไม่ได้เลย (ทุกคนในทีมเป็นคนเปิด PR นี้พร้อมกันได้ไงเนี่ย 🤔)"
    )
