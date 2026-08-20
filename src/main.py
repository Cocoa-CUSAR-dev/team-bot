"""Runs the Discord client and the GitHub webhook receiver as two tasks in
one process/event loop -- there's no reason to split this into two deploys
for a bot this small, and it keeps the Discord client's channel cache
(client.get_channel) warm and ready for the webhook handler to use.
"""

import asyncio

import uvicorn
from fastapi import FastAPI

from src.config import settings
from src.discord_bot import client
from src.github_webhook import router as github_router

app = FastAPI(title="review-bot")
app.include_router(github_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "discord_ready": str(client.is_ready())}


async def main() -> None:
    server = uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=settings.WEBHOOK_PORT, log_level="info")
    )
    await asyncio.gather(
        client.start(settings.DISCORD_BOT_TOKEN),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
