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

    # Guards POST /internal/daily-reminder -- a plain shared-secret header,
    # not GitHub's HMAC scheme, since the caller here is a GitHub Actions
    # cron we control, not GitHub's own webhook delivery.
    INTERNAL_TRIGGER_SECRET: str

    # --- /myreviews slash command -------------------------------------
    # All four default to "" ON PURPOSE. Settings is instantiated at import
    # time, so a field with no default turns a missing env var into an
    # import-time crash that takes the WHOLE service down -- GitHub webhook
    # assignments included, not just the new command. (Exactly how the
    # chatbot's CHATBOT_SERVICE_KEY took that service down on 2026-09-05.)
    # Adding a feature must not be able to break the bot that already works,
    # so the interactions endpoint checks for its key at request time and
    # returns a clear error instead.
    #
    # Discord Developer Portal > your app > General Information > Public Key.
    # This is the only one the RUNNING SERVICE needs -- it verifies that an
    # incoming interaction really came from Discord (Ed25519).
    DISCORD_PUBLIC_KEY: str = ""

    # The three below are only read by `python -m src.register_commands`,
    # the one-off script that tells Discord the command exists. The server
    # never uses them.
    DISCORD_APP_ID: str = ""
    # Needed ONLY to register the command, never to serve it -- there's no
    # gateway connection and no bot process to keep alive.
    DISCORD_BOT_TOKEN: str = ""
    # Registering per-guild applies instantly; global commands take up to an
    # hour to propagate. Right-click the server > Copy Server ID.
    DISCORD_GUILD_ID: str = ""

    WEBHOOK_PORT: int = 8090


settings = Settings()  # type: ignore[call-arg]
