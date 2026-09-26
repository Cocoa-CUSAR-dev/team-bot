"""Run once (and again only if the command's name/description changes):

    python -m src.register_commands

Tells Discord that /myreviews exists. This is the ONLY thing that needs a
bot token, and it needs it here, not in the running service -- there's no
gateway connection to keep alive, so the deployed app never holds one.

Registers per-guild rather than globally: guild commands appear instantly,
global ones take up to an hour to propagate, which is a miserable feedback
loop for a 4-person team's internal tool.
"""

import asyncio

import httpx

from src.config import settings
from src.discord_interactions import MYREVIEWS_COMMAND

COMMANDS = [
    {
        "name": MYREVIEWS_COMMAND,
        "description": "ดูว่าตอนนี้เราถือรีวิว PR อะไรค้างอยู่บ้าง",
        "type": 1,  # CHAT_INPUT
    }
]


async def main() -> None:
    missing = [
        name
        for name, value in (
            ("DISCORD_APP_ID", settings.DISCORD_APP_ID),
            ("DISCORD_BOT_TOKEN", settings.DISCORD_BOT_TOKEN),
            ("DISCORD_GUILD_ID", settings.DISCORD_GUILD_ID),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            f"missing {', '.join(missing)} -- see .env.sample. These are only "
            "needed to register the command, not to run the service."
        )

    url = (
        f"https://discord.com/api/v10/applications/{settings.DISCORD_APP_ID}"
        f"/guilds/{settings.DISCORD_GUILD_ID}/commands"
    )
    async with httpx.AsyncClient() as client:
        # PUT (bulk overwrite) rather than POST: re-running this is then
        # idempotent instead of erroring or quietly creating duplicates.
        response = await client.put(
            url,
            headers={"Authorization": f"Bot {settings.DISCORD_BOT_TOKEN}"},
            json=COMMANDS,
            timeout=30,
        )
        if response.status_code >= 400:
            raise SystemExit(f"Discord rejected it ({response.status_code}): {response.text}")

    print(f"registered: {', '.join('/' + c['name'] for c in COMMANDS)}")


if __name__ == "__main__":
    asyncio.run(main())
