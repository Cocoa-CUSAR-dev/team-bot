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
2. If the PR title carries a task key that someone already holds, it goes
   straight to them (see *Task grouping* below). Otherwise the picker
   (`src/picker.py`) excludes the PR's author, finds whoever among the
   remaining 3 has been dealt the least work in the last 14 days (finished
   or not), and picks randomly among anyone tied for that minimum.
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

7. Anyone can run **`/myreviews`** in Discord to see what they're currently
   holding, without waiting for the 19:00 post. Reply goes in-channel and
   marks anything over 2 days old with 🔥, the same threshold the daily
   reminder's dragon uses.

## Task grouping

Put a task key in the PR title and every PR carrying it goes to one reviewer —
first one picked normally, the rest follow it. No key, no change in behaviour.

```
feat(sentry): add error tracking — web-app (X-2d)      -> x2d
feat(x6d): gate production deploy behind a GitHub Env  -> x6d
test(US2-5): autofill pipeline parity e2e (#106)       -> us25
Feat web UI notification                               -> none, picker decides
```

A key is a bracketed token with **a letter and a digit** — that rules out
`(#106)` and `feat(logging):`. Normalised `[^a-z0-9]` → `""`, so `(X-2d)` ==
`(x2d)`, and `US2-5` == `US25` (don't mix spellings). Parser and its edge
cases: `src/grouping.py`, `tests/test_grouping.py`.

Never routes a PR to its own author — falls back to the picker.

Follow-on announcements name the predecessor PR and its age, since a group's
PRs often land days apart.

**Load** is work *dealt out* in the last 14 days, finished or not — not the
size of your open queue. Ties break on who has less still unreviewed.

Counting only open reviews punished the fast reviewer: finishing dropped you
to zero and the next PR came straight back, while sitting on six untouched
PRs kept you looking busy. On live data that put the person with 30 finished
and 2 open first in line for the next PR; under the current rule they're last.

One task costs `1 + (n-1)*0.5` points, so 5 PRs of one task = 3, five loose
PRs = 5. Knobs, both in `src/reviews.py`: `LOAD_WINDOW` (14 days) and
`FOLLOW_ON_PR_WEIGHT` (`1.0` = plain per-PR count, `0.0` = whole task costs 1).

**Out-of-order events:** a PR can be merged seconds after it opens, and the
two webhook deliveries can be processed in either order. A `closed` handled
before its own `opened` used to leave an assignment nothing could ever resolve
(chatbot#72, merged 4s before its assignment row was written -- it sat in the
daily reminder until someone complained). Every close is now recorded in
`closed_pr`, and an `opened` that finds its PR already there skips assignment
entirely. Create the table with `python -m src.migrate_closed_pr`.

**Migration — run before deploying**, `create_all` won't add the column and
every request selects it:

```bash
python -m src.migrate_group_key           # dry run
python -m src.migrate_group_key --apply   # + backfills keys from stored titles
```

## Posting through the relay (optional, recommended)

Render's free tier NATs outbound traffic through an IP shared with everyone
else on it, and on 2026-10-03 Discord's edge began refusing that IP outright
-- `429 Retry-After 491`, then `3242` the same evening -- while the same
webhook answered a laptop instantly with 4 of 5 requests left in its bucket.
Nothing the bot sent was over any limit; the address it sent from was.

`relay/` is a Cloudflare Worker that posts on the service's behalf. Discord
sits behind Cloudflare, so the request barely leaves the network.

```bash
cd relay
npx wrangler deploy
npx wrangler secret put DISCORD_WEBHOOK_URL   # the channel it may post to
npx wrangler secret put RELAY_SECRET          # any long random string
```

Then on Render set `DISCORD_RELAY_URL` to the deployed Worker URL and
`DISCORD_RELAY_SECRET` to the same string. Both must be set or the relay is
ignored and posting stays direct -- a URL without the secret would be rejected
by the Worker on every message. `/internal/webhook-check` reports `route` so
you can see which one is live.

The Worker holds the Discord webhook URL itself, so the service never sends
it: the relay can reach exactly one channel, which makes its own URL and
secret far less dangerous to leak than the webhook would be. Discord's status
and `Retry-After` are passed back untouched, so the rate-limit handling and
the outbox cooldown keep working through it.

There is no fallback from relay to direct. A silent fallback would resume
posting from the very IP the relay exists to avoid, precisely when something
is already wrong; the outbox holds the message instead.

## If Discord won't take a message

Every post goes through a durable queue (`pending_announcement`, see
`src/outbox.py`). If Discord refuses it, the message is stored and retried
instead of being lost, and anything posted afterwards queues behind it rather
than overtaking it -- a follow-on assignment saying "ต่อจาก X ที่ถืออยู่" has to
arrive after the message it refers to.

The queue is drained on every GitHub webhook delivery, and by a cron every 15
minutes (`.github/workflows/flush-outbox.yml`) for quiet stretches. Manually:

```bash
curl -X POST "$REVIEW_BOT_URL/internal/flush-outbox" -H "X-Internal-Secret: $SECRET"
```

This exists because of 2026-10-03: Discord answered the deployed service with
`429 Retry-After 491` while the same webhook answered a laptop instantly with
4 of 5 requests left in the bucket -- an IP-level limit on the shared hosting
egress, nothing the bot did. Two things made it much worse than it had to be,
both now fixed: `_post` slept for the full Retry-After *inside the request*,
which blew GitHub's ~10s delivery timeout and caused a redelivery (and a
second assignment); and the message itself was then simply gone.

A message Discord rejects 5 times is left behind rather than blocking
everything behind it -- at that point it's malformed, not rate-limited.
Diagnostics: `/internal/webhook-check` (verifies the URL without posting) and
`/internal/test-announce` (runs the announcement path and returns the error
instead of swallowing it).

Load is derived from an event log (`review_assignment`, open/resolved rows),
not a mutable counter — a missed or duplicated webhook event can't leave a
raw counter permanently wrong the way it could with `count += 1` / `count -= 1`.

### Why `/myreviews` is a slash command, not "@น้องโกโก้ myreviews"

Reading channel messages — which is what reacting to an @mention means —
needs a live gateway WebSocket and the Message Content intent, i.e. an
always-on process. That's exactly the requirement this service was built to
avoid (see the top of this file). A slash command arrives as a plain HTTPS
POST instead, so it runs on the same stateless free-tier service as
everything else, with no bot process to keep alive.

The bot token below is used **only** to register the command with Discord,
once, from your laptop. The deployed service never holds or uses it.

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

### `/myreviews` setup

One-time, in the [Discord Developer Portal](https://discord.com/developers/applications):

1. **New Application** (or reuse an existing one). From *General Information*
   copy the **Application ID** → `DISCORD_APP_ID`, and the **Public Key** →
   `DISCORD_PUBLIC_KEY`.
2. **Bot → Reset Token** → `DISCORD_BOT_TOKEN`. Only needed for step 5; the
   deployed service never uses it, so it doesn't go in the Render env.
3. Server ID (Developer Mode on → right-click the server → Copy Server ID)
   → `DISCORD_GUILD_ID`.
4. Set **Interactions Endpoint URL** to `<REVIEW_BOT_URL>/discord/interactions`
   and save. Discord verifies it by sending deliberately-invalid signatures
   and expecting 401s — so the service must already be deployed with
   `DISCORD_PUBLIC_KEY` set before this save will succeed.
5. Register the command from your laptop:
   ```bash
   python -m src.register_commands
   ```
6. Invite the app to the server with the `applications.commands` scope
   (OAuth2 → URL Generator). No bot permissions are needed beyond that.

**Only `DISCORD_PUBLIC_KEY` needs to be set on Render.** The other three are
laptop-only, for step 5.

Same cold-start caveat, but sharper here: Discord gives an interaction **3
seconds** to respond. If the service has spun down, the first `/myreviews`
will show "The application did not respond" — run it again a few seconds
later and it works. The 19:00 cron also keeps it warm each evening.

## Not handled (by design, out of scope for this bot)

- Requesting review on GitHub itself — this only posts in Discord.
- Re-review after "changes requested" — only the initial `opened` event
  triggers an assignment.
- Self-serve account linking — 4 fixed people, seeded directly instead.
- Reacting to @mentions or free-text keywords — needs an always-on gateway
  connection; `/myreviews` covers the same need over plain HTTP. See above.
- Checking *someone else's* review load — `/myreviews` is self-only. A
  `user:` option would be easy to add if the team wants it for nudging.
