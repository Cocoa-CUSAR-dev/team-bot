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
   remaining 3 carries the fewest review points, and picks randomly among
   anyone tied for that minimum.
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

## Task grouping — keeping one task with one reviewer

One task often spans several repos, so it opens several PRs. Assigned
independently, they scatter across the team and somebody has to transfer them
back by hand. Instead, the bot reads the **task key** out of the PR title:
the first PR of a key goes through the normal picker, and every later PR
carrying that key goes to whoever already holds it.

### How to use it

Put the key in the PR title. Both styles the team already writes work:

```
feat(sentry): add error tracking — web-app (X-2d)     -> key x2d
feat(x6d): gate production deploy behind a GitHub Env  -> key x6d
test(US2-5): autofill pipeline parity e2e (#106)       -> key us25
```

Rules, in full:

- A key is a bracketed token containing **both a letter and a digit**. That's
  what separates `(X-2d)` from `(#106)` (a PR reference) and `feat(logging):`
  (a plain conventional-commit scope) — neither of those is treated as a key.
- Case and hyphens don't matter: `(X-2d)`, `(x-2d)` and `(x2d)` are one group.
  The flip side is that `US2-5` and `US25` collide; use one spelling.
- **No key is completely fine.** The PR just goes through the normal
  load-balancing picker, exactly as before. Most PRs have no key. The bot
  adds one quiet line to the announcement mentioning the option — delete
  `NO_KEY_HINT` in `src/discord_notify.py` if it gets old.
- The bot only groups PRs whose reviewer isn't the PR's own author.

When a PR is routed by group, the announcement says so outright, naming the
earlier PR and how long ago it was assigned — PRs of one task often land days
apart, and without a reason the pick just looks like the bot ignoring load.

### What a grouped task costs its reviewer

The first PR of a task costs a full point; every further PR of that same task
costs **half**. So 5 PRs of one task = `1 + 4 × 0.5` = **3 points**. Separate
un-keyed PRs still cost 1 each, so five of those cost 5.

Both extremes were worse than this. Charging all 5 points meant the holder
was skipped for days and then — when the whole batch merged at once — dropped
to zero and caught the next several PRs in a row, a bigger swing than the one
being fixed. Charging 1 point total meant someone already reading five diffs
looked exactly as free as someone holding a single PR.

To change the weighting, edit `FOLLOW_ON_PR_WEIGHT` in `src/reviews.py`
(`0.5` → `1.0` restores plain per-PR counting; `0.0` makes a whole task cost
one point).

### Migrating an existing database

`src/seed.py` only runs `create_all`, which never alters an existing table,
so a DB seeded before this feature needs the column added once. **Run this
before deploying the new code** — the service selects `group_key` and will
error on every request until the column exists.

```bash
python -m src.migrate_group_key           # dry run, prints what it would do
python -m src.migrate_group_key --apply
```

It also backfills keys from the PR titles already stored on old rows, so
tasks that are mid-flight at deploy time group correctly instead of each
looking brand new. Safe to re-run.

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
