import os

import uvicorn
from fastapi import FastAPI

from src.config import settings
from src.github_webhook import router as github_router
from src.internal import router as internal_router

app = FastAPI(title="review-bot")
app.include_router(github_router)
app.include_router(internal_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    # Render assigns its own port via the PORT env var and health-checks
    # exactly that port -- ignoring it and binding to a fixed port instead
    # is why a deploy can build fine, start fine, and still hang "in
    # progress" forever (Render's port scanner never finds it listening
    # where expected). PORT takes priority when Render sets it; WEBHOOK_PORT
    # is just the local-dev fallback.
    port = int(os.environ.get("PORT", settings.WEBHOOK_PORT))
    uvicorn.run(app, host="0.0.0.0", port=port)
