from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres, not SQLite -- if this ever runs on Render like the rest of
    # this project's services, Render's default disk is ephemeral and wipes
    # a SQLite file on every deploy/restart. A tiny free-tier Neon DB (same
    # provider already used elsewhere in this project) avoids that entirely.
    # SQLAlchemy async needs the asyncpg driver in the URL scheme.
    DATABASE_URL: str

    # A plain Discord incoming webhook URL -- Settings > Integrations >
    # Webhooks on the target channel. Treat this as a secret: whoever has it
    # can post to that channel.
    DISCORD_WEBHOOK_URL: str

    # Verifies incoming GitHub webhook payloads are actually from GitHub
    # (HMAC signature check) -- set the same value in each repo's webhook
    # config (Settings > Webhooks > Secret).
    GITHUB_WEBHOOK_SECRET: str

    WEBHOOK_PORT: int = 8090


settings = Settings()  # type: ignore[call-arg]
