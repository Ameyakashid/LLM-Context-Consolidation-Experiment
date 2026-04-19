# Syncall — Taskwarrior ↔ Google Calendar bidirectional sync

## TL;DR

A background daemon keeps your Taskwarrior tasks and a named Google
Calendar in sync. It polls every 10 minutes by default. Taskwarrior is
canonical: when the same task is edited in both places between syncs,
Taskwarrior wins. Feature is OFF by default — flip `SYNCALL_ENABLED=true`
in your `.env` to turn it on.

## Prerequisites

1. **Taskwarrior installed.** `task` CLI on PATH.
   - macOS: `brew install task`
   - Windows: `choco install task`
   - Debian/Ubuntu: `apt install taskwarrior`
2. **`TASKWARRIOR_ENABLED=true`** in `.env`. The daemon reads from the
   same data dir the bot writes to (`workspace/data/taskwarrior/`).
3. **Google OAuth desktop-client JSON.** The same file Task 14's GCal
   MCP uses. Path in `.env` as `GOOGLE_OAUTH_CREDENTIALS`. No second set
   of credentials is needed; syncall requests the calendar scope, which
   is a superset of the read-only scope Task 14 uses.
4. **A Google Calendar named in `SYNCALL_GCAL_CALENDAR`.** The calendar
   must already exist in your Google account. Syncall will NOT create
   it for you.

## How to turn it on

1. Open your `.env` and set:
   ```
   SYNCALL_ENABLED=true
   SYNCALL_GCAL_CALENDAR=ADHD-Assistant   # or whatever you named it
   GOOGLE_OAUTH_CREDENTIALS=/absolute/path/to/your/oauth.keys.json
   TASKWARRIOR_ENABLED=true
   ```
2. Run `python setup_workspace.py` to create the syncall cache dir and
   the repo-scoped taskrc file.
3. **One-time OAuth consent** — run `tw_gcal_sync` interactively once,
   not from the daemon. In a terminal:
   ```
   cd <repo-root>
   python -m syncall.scripts.tw_gcal_sync \
     --gcal-calendar ADHD-Assistant \
     --google-secret $GOOGLE_OAUTH_CREDENTIALS \
     --custom-combination-savename adhd-assistant \
     --sync-all-tw-tasks
   ```
   A browser pops open, you click "Allow", and syncall writes a token
   pickle to `~/.gcal_credentials.pickle`. This path is hardcoded
   upstream and cannot be redirected — see "Why the token is in your
   home dir" below. The pickle file refreshes itself automatically on
   subsequent runs; you only do the interactive consent once.
4. Start the bot: `python start.py`. Syncall comes up as a child process
   alongside the gateway and dashboard. Watch `workspace/data/syncall_daemon.log`
   for a healthy `sync OK in 2.3s` line once per 10 minutes.

## Conflict policy — Taskwarrior wins

The bot, MagicMirror, the dashboard, and all heartbeat hooks read from
Taskwarrior. Google Calendar is a mirror + convenience input surface.
When a conflict happens (the same task edited on both sides between
two syncs), Taskwarrior's version replaces the calendar's version on
the next tick. The env var
`SYNCALL_RESOLUTION_STRATEGY=tw_wins` encodes this policy.

Change it to `gcal_wins` if you prefer calendar-wins semantics, or to
`most_recent` / `least_recent` for timestamp-based resolution. All four
map to upstream syncall class names (`AlwaysSecondRS`, `AlwaysFirstRS`,
`MostRecentRS`, `LeastRecentRS`) — both the alias and the class name
are accepted.

## New-event-in-GCal behaviour — the one implicit task creation

When you add an event to the calendar that has no Taskwarrior
counterpart, the next sync pulls it into Taskwarrior as a new task.
This is the one form of implicit task creation in the bot — normally
the bot never creates tasks without you asking. If you drag an event
around in the calendar app, it becomes a Taskwarrior task with the
matching title and due date. The bot does not narrate this; you see
it next time you run `task list` or check the dashboard.

If you want to avoid this, do not add events to the synced calendar.
Use a different calendar for non-task events.

## Poll cadence

Default: 600 seconds (10 minutes). Configurable via `SYNCALL_POLL_SECONDS`.
Minimum 60 — the daemon rejects lower values to stay under Google
Calendar API quotas. A typical sync makes 3–10 API calls; 144 syncs/day
is comfortably under the 1,000,000/day default project quota.

## How to tell it is working

Log path: `workspace/data/syncall_daemon.log`

Healthy line (once per 10 min):
```
syncall_daemon INFO sync OK in 2.3s
```

Expected-error lines (network flap, OAuth expired, etc.) — the daemon
logs a WARNING and continues to the next tick:
```
syncall_daemon WARNING sync FAILED code=1 in 0.8s. stderr tail: ...
```

Pre-flight errors that stop the daemon with exit code 2:
- `'task' binary not on PATH` — install Taskwarrior.
- `could not import syncall` — verify `vendor/syncall/` is intact and
  `pip install -r requirements.txt` completed.
- `GOOGLE_OAUTH_CREDENTIALS points at missing file` — download the
  OAuth JSON from Google Cloud Console and point the env var at it.

## How to turn it off

Flip `SYNCALL_ENABLED=false` in `.env` and restart (`python start.py`).
The daemon subprocess is not spawned. Existing Taskwarrior data and
calendar events are preserved on both sides; syncall is stateless
between runs except for its cache dir.

To wipe syncall's side-mapping cache and force a fresh first-sync:
delete `workspace/data/syncall_cache/syncall/` before restarting. The
next run re-discovers items on both sides.

## Troubleshooting

**OAuth expired / invalid token.** Delete `~/.gcal_credentials.pickle`
and re-run the interactive `tw_gcal_sync` command from step 3 above.

**"ModuleNotFoundError: No module named 'syncall'"** — `vendor/syncall/`
is missing or `PYTHONPATH` is not set. The daemon prepends vendor to
`sys.path` automatically; if you are running `tw_gcal_sync` by hand,
run it from the repo root with `PYTHONPATH=vendor/syncall`.

**"Could not determine a valid taskwarrior config file"** — the daemon
writes a repo-scoped taskrc at `workspace/data/syncall_cache/taskrc`
and passes `TASKRC=<that path>` to the subprocess. If that file is
missing, re-run `python setup_workspace.py` to regenerate it.

**Historical migrated tasks flooding your calendar on first sync.**
Task 16 sub-02's migration CLI tags imported tasks with `migrated_<hex>`.
Set `SYNCALL_TW_FILTER="-migrated"` in `.env` to exclude every migrated
task from being pushed to calendar. New tasks the bot creates after
migration day will still sync normally.

**Why the token is in your home dir.** Syncall hardcodes the OAuth
pickle path to `Path.home() / ".gcal_credentials.pickle"`. There is no
CLI flag or env var to redirect it without patching the vendor source.
The file is gitignored as a belt-and-braces in case a stray copy ever
lands under the repo root. If you also run the upstream `tw_gcal_sync`
outside the repo, you will share the same token cache — this is syncall's
design and is consistent across installs.
