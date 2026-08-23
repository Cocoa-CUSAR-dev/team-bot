# review-bot

Discord bot that fairly assigns a PR reviewer when a PR opens, and tracks
who's currently loaded down with reviews. Separate service, separate DB from
the rest of the project on purpose — a bug or outage here should never touch
the actual product.

Posts through a plain Discord **incoming webhook**, not a full bot
client/token — no gateway connection to keep alive, so there's no
always-on-process requirement; a normal (even free-tier) web host is fine.

## How it works

1. GitHub webhook (`pull_request: opened`) hits `POST /github/webhook`.
2. The picker (`src/picker.py`) excludes the PR's author, finds whoever
   among the remaining 3 has the fewest currently-open review assignments,
   and picks randomly among anyone tied for that minimum.
3. Posts in the configured Discord channel via the webhook, as **น้องโกโก้**,
   tagging that person (`<@discord_id>`) with one of a few random กวนๆ lines.
4. On `pull_request: closed` (merged or not), their open assignment for
   that PR is marked resolved — their load drops back down.
5. If there's a genuine tie for fewest-loaded, whoever was *just* assigned
   (globally, any repo) is skipped unless they're the only person left in
   the tie — so a real coin-flip repeat doesn't feel like a bias, without
   changing the "PRs > people forces a repeat" case, which is correct.
6. Every evening at 19:00 Asia/Bangkok, a GitHub Actions cron (in this repo,
   `.github/workflows/daily-reminder.yml`) hits `POST /internal/daily-reminder`,
   which posts one message listing every still-open review, tagging each
   person. Runs on a schedule *outside* review-bot itself on purpose (see
   below) rather than an in-process scheduler.

Load is derived from an event log (`review_assignment`, open/resolved rows),
not a mutable counter — a missed or duplicated webhook event can't leave a
raw counter permanently wrong the way it could with `count += 1` / `count -= 1`.

## First-time setup

```bash
cp .env.sample .env   # fill in DATABASE_URL, DISCORD_WEBHOOK_URL, GITHUB_WEBHOOK_SECRET
```

Copy `roster.local.json.example` to `roster.local.json` (gitignored, never
committed — real teammates' info doesn't belong in tracked source) and fill
in the real 4-person roster. Each person's `discord_id` is their **numeric**
Discord user ID (Developer Mode on in Discord settings → right-click them →
Copy User ID) — not their username; a plain webhook has no way to look up a
username, only a raw ID resolves to a real ping. No self-serve linking
command for a team this size. Then run once:

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

### Daily reminder setup

This repo's GitHub Actions secrets (Settings → Secrets and variables →
Actions) need:
- `REVIEW_BOT_URL` — the deployed base URL (e.g. `https://team-bot-vszf.onrender.com`)
- `REVIEW_BOT_INTERNAL_SECRET` — same value as `INTERNAL_TRIGGER_SECRET` in the deployed env

Render's free tier spins down when idle — the first cron hit of the day
pays a ~50s cold-start, which is fine for a once-a-day job. Test it anytime
without waiting for 19:00 via the workflow's "Run workflow" button
(`workflow_dispatch`) on the Actions tab.

## Not handled (by design, out of scope for this bot)

- Requesting review on GitHub itself — this only posts in Discord.
- Re-review after "changes requested" — only the initial `opened` event
  triggers an assignment.
- Self-serve account linking — 4 fixed people, seeded directly instead.
