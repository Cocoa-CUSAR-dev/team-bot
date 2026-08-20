import uvicorn
from fastapi import FastAPI

from src.config import settings
from src.github_webhook import router as github_router

app = FastAPI(title="review-bot")
app.include_router(github_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.WEBHOOK_PORT)
