"""Sets dummy env vars BEFORE any `src` import -- config.py instantiates its
Settings object at module import time (same pattern as the chatbot repo).
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test/test")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")
