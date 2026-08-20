"""น้องโกโก้ -- the bot's persona/display name in every message it posts.

Needs the "Server Members Intent" toggle ON in the Discord Developer Portal
(Bot page) -- without it, client.get_all_members() only ever sees the bot
itself, and username resolution below silently fails for everyone else.
"""

import logging
import random

import discord

from src.config import settings

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.members = True  # required to resolve a username to a mentionable member
client = discord.Client(intents=intents)

BOT_PERSONA = "🍫 น้องโกโก้"

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


def _resolve_mention(discord_username: str) -> str:
    member = discord.utils.get(client.get_all_members(), name=discord_username)
    if member is None:
        logger.warning(
            "could not resolve discord_username=%s to a guild member -- "
            "check Server Members Intent is on and the username is exact",
            discord_username,
        )
        return f"@{discord_username}"  # visible fallback, just not a real ping
    return member.mention


async def announce_assignment(*, repo: str, pr_number: int, pr_title: str, pr_url: str,
                               reviewer_discord_username: str, author_github_username: str) -> None:
    channel = client.get_channel(settings.DISCORD_CHANNEL_ID)
    if channel is None:
        raise RuntimeError(f"channel {settings.DISCORD_CHANNEL_ID} not found/not cached yet")

    mention = _resolve_mention(reviewer_discord_username)
    teasing = random.choice(TEASING_LINES)

    await channel.send(
        f"{BOT_PERSONA}: {mention} ถึงคิวรีวิวแล้วจ้า! {teasing}\n"
        f"**{repo}#{pr_number}** — {pr_title}\n"
        f"เปิดโดย `{author_github_username}` — {pr_url}"
    )


async def announce_no_reviewer_available(*, repo: str, pr_number: int, pr_title: str) -> None:
    """Only fires if literally everyone linked is the PR author -- shouldn't
    happen with a real 4-person roster on someone else's repo, but silently
    dropping the PR would be worse than saying so.
    """
    channel = client.get_channel(settings.DISCORD_CHANNEL_ID)
    if channel is None:
        return
    await channel.send(
        f"{BOT_PERSONA}: **{repo}#{pr_number}** — {pr_title}\n"
        f"⚠️ หาคนรีวิวให้ไม่ได้เลย (ทุกคนในทีมเป็นคนเปิด PR นี้พร้อมกันได้ไงเนี่ย 🤔)"
    )
