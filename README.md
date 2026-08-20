# review-bot

Discord bot that fairly assigns a PR reviewer when a PR opens, and tracks
who's currently loaded down with reviews. Separate service, separate DB from
the rest of the project on purpose — a bug or outage here should never touch
the actual product.

## How it works

1. GitHub webhook (`pull_request: opened`) hits `POST /github/webhook`.
2. The picker (`src/picker.py`) excludes the PR's author, finds whoever
   among the remaining 3 has the fewest currently-open review assignments,
   and picks randomly among anyone tied for that minimum.
3. Posts in the configured Discord channel, tagging that person.
4. On `pull_request: closed` (merged or not), their open assignment for
   that PR is marked resolved — their load drops back down.

Load is derived from an event log (`review_assignment`, open/resolved rows),
not a mutable counter — a missed or duplicated webhook event can't leave a
raw counter permanently wrong the way it could with `count += 1` / `count -= 1`.

## First-time setup

```bash
cp .env.sample .env   # fill in DATABASE_URL, DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, GITHUB_WEBHOOK_SECRET
```

In the Discord Developer Portal, on the bot's page, turn on **Server
Members Intent** — without it the bot can't resolve a Discord username to
a real, pingable member.

Copy `roster.local.json.example` to `roster.local.json` (gitignored, never
committed — real teammates' usernames don't belong in tracked source) and
fill in the real 4-person roster. No self-serve linking command for a team
this size. Then run once:

```bash
python -m src.seed
```

Run it:

```bash
python -m src.main
```

Point each of the 6 repos' Settings → Webhooks (or one org-level webhook, if
that's set up) at this service's `/github/webhook` URL, content type
`application/json`, "Pull requests" event only, secret matching
`GITHUB_WEBHOOK_SECRET`.

## Not handled (by design, out of scope for this bot)

- Requesting review on GitHub itself — this only posts in Discord.
- Re-review after "changes requested" — only the initial `opened` event
  triggers an assignment.
- Self-serve account linking — 4 fixed people, seeded directly instead.
