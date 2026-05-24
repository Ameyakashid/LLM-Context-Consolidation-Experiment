# Calendar — Google Calendar Setup

This file is for you, the human. It explains how calendar integration works, how to turn it on, how to re-authorize it when it breaks, and how to turn it off.

## TL;DR

1. Put `GOOGLE_CALENDAR_ENABLED=true` in your `.env`.
2. Run `python setup_workspace.py`. It builds the calendar MCP server.
3. Run `npm run auth` inside `mcp/google-calendar/` — a browser opens, you sign in, done.
4. Morning check-ins now start with today's events. That's it.

If something breaks, skim *"When It Breaks"* below. It's usually expired tokens.

---

## What This Does

Two things, separately:

**1. Calendar tools for the assistant.** When enabled, three read-only tools appear in the toolchain:
- `get_upcoming_events` — next N hours from your primary calendar
- `list_events_in_window` — arbitrary time window, one or many calendars
- `check_free_busy` — busy/free intervals

The assistant decides when to call them. You don't have to ask by name.

**2. Morning context injection.** During the `morning_motivation` and `morning_plan` check-ins, today's schedule is auto-injected into the system prompt. You get a single line per event: `- 09:00 Standup (Zoom)`. No events? You get *"(nothing scheduled — free day)"*. Capped at 8 items so it stays readable.

Other check-ins (afternoon, evening) don't fetch. Normal chat turns don't fetch. Morning-only, and only when your state is `baseline`, `focus`, `avoidance`, or `rsd` — hyperfocus and overwhelm skip the injection deliberately, to avoid piling more on an already-overloaded state.

## What This Doesn't Do

- No writes. No event creation, no deletion, no edits. Read-only by design.
- No polling in the background. Calendar is pulled on demand.
- No multi-account juggling. One Google account, the one you authorize.

## First-Time Setup

You need Node 18+ on your path. Verify: `node --version`.

1. **Enable the flag.** Add to your `.env`:

   ```
   GOOGLE_CALENDAR_ENABLED=true
   ```

2. **Run the setup script.**

   ```
   python setup_workspace.py
   ```

   It builds the vendored `mcp/google-calendar/` server (runs `npm ci && npm run build`). Takes a minute.

3. **Authorize.** Inside the repo:

   ```
   cd mcp/google-calendar
   npm run auth
   ```

   A browser window opens. Sign in with the Google account you want to read. Grant calendar read permission. Close the window when it says "authentication successful."

   Tokens land in `~/.nanobot/data/google-calendar/tokens.json`. They refresh automatically until the refresh token expires (typically 6 months of inactivity, or whenever Google decides).

4. **Restart the gateway.** Calendar tools register at startup, so you need to restart after enabling the flag.

## When It Breaks

**Morning check-in shows:** *"Calendar unavailable — the user's Google authorization has expired."*

That's this file's cue to you. Almost always it means tokens expired. Fix:

```
cd mcp/google-calendar
npm run auth
```

Sign in again. Restart the gateway. Done.

If the browser flow fails, check:
- Is the Google Cloud project still active? (They auto-archive idle projects.)
- Did you rotate the OAuth client secret?
- Is `tokens.json` write-protected or on a mounted path without write access?

**Calendar tools missing from the agent.** The flag isn't set or the MCP server isn't connecting:

- Verify `.env` has `GOOGLE_CALENDAR_ENABLED=true` (lowercase `true` is fine).
- Check `~/.nanobot/workspace/config.json` — it should reference the built server under `mcp.servers.google-calendar`.
- Watch gateway startup logs for `google-calendar` errors.

**Events duplicate across calendars.** You probably authorized an account that has shared calendars you forgot about. Fix: revoke in https://myaccount.google.com/permissions, re-run `npm run auth`, and pick a narrower account — or call `list_events_in_window` with a single `calendar_ids` entry to scope it.

## Turning It Off

Flip the flag:

```
GOOGLE_CALENDAR_ENABLED=false
```

Restart the gateway. The three tools vanish, the morning injection stops. Your tokens stay on disk (delete `~/.nanobot/data/google-calendar/tokens.json` if you want them gone).

## Timezone

The hook and tools read `NANOBOT_TIMEZONE` from your env (falls back to UTC). Set it to your actual IANA zone — e.g. `America/New_York`, `Asia/Kolkata` — so "today" lines up with your wall clock.

## Privacy Notes

- Event data is **not** persisted. It lives only in the process memory cache (60 seconds TTL, 128-entry FIFO) and is embedded in the model prompt for morning check-ins.
- Tokens live on your local disk at `~/.nanobot/data/google-calendar/tokens.json`. They never leave your machine.
- MCP calls go from your machine → local subprocess → Google Calendar API directly. No intermediate cloud.

## Cost

Small. Morning check-ins fire 1-2x/day and inject ~50-400 tokens of calendar context. Agentic tool calls (on top of the morning injection) are opt-in by the model and capped by nanobot's per-iteration budget.

## Troubleshooting Checklist

- [ ] `.env` has `GOOGLE_CALENDAR_ENABLED=true`
- [ ] `node --version` shows 18+
- [ ] `mcp/google-calendar/dist/` exists (setup_workspace built it)
- [ ] `~/.nanobot/data/google-calendar/tokens.json` exists and is recent
- [ ] Gateway logs at startup don't show calendar errors
- [ ] `NANOBOT_TIMEZONE` is set to your actual zone

If all six are green and it still fails, paste the `calendar_hook` WARNING log line into an issue and we'll dig.
