# MAC_PATHS.md — where your data lives on the Mac

On Windows the bot writes everything under `workspace/data/` inside the repo.
On a Mac, Apple's convention is to put persistent user data under
`~/Library/Application Support/` and logs under `~/Library/Logs/`. This file
explains what moves where and how to run the one-shot migration.

You only run this **once**, the first time you set up the bot on the Mac.
It does not touch the Windows repo; rollback is a single `rm -rf`.

## What moves where on Mac

| Windows (source)                              | Mac (target)                                                                 | Holds                                                           |
|-----------------------------------------------|------------------------------------------------------------------------------|-----------------------------------------------------------------|
| `workspace/data/`                             | `~/Library/Application Support/adhd-assistant/data/`                         | ADHD stores (check-ins, buffers, memories, cognitive state) + Dream persistence (`dream_last_run.json`, `dream_sessions.jsonl`) |
| `workspace/data/taskwarrior/`                 | `~/Library/Application Support/adhd-assistant/taskwarrior/`                  | Taskwarrior `.data` files                                        |
| `gcp-oauth.keys.json` (repo root, gitignored) | `~/Library/Application Support/adhd-assistant/oauth/gcp-oauth.keys.json`     | Google OAuth client secrets                                      |
| (written on first Mac run)                    | `~/Library/Application Support/adhd-assistant/oauth/mcp-token.json`          | Google Calendar MCP refresh tokens                               |
| (written on first Mac run)                    | `~/Library/Logs/adhd-assistant/`                                             | Runtime stdout / stderr from the LaunchAgent (sub-04)            |

The pickle at `~/.gcal_credentials.pickle` is **not** migrated. Upstream
`vendor/syncall/` hardcodes `Path.home() / ".gcal_credentials.pickle"`; on
first launch of `start.py` on the Mac, syncall re-runs the OAuth flow and
writes a fresh pickle there. This is the expected path — see
"Troubleshooting" below.

## How to run the migration

From the repo root, in Terminal:

```sh
# 1. Dry-run: show what would be copied without touching disk
python scripts/migrate_windows_to_mac.py

# 2. Actual copy (reversible — source is never modified)
python scripts/migrate_windows_to_mac.py --apply

# 3. Open .env and uncomment the `=== macOS Conventional Paths ===` block
#    near the bottom. Save.

# 4. Restart the bot so the new env vars are read
.venv/bin/python start.py
```

The migration writes `migration_windows_to_mac.log` inside the target base,
appending one timestamped block per run. Re-running `--apply` is safe —
every entry skips when the target is already populated.

## How to roll back

```sh
# Remove everything the migration created
rm -rf ~/Library/Application\ Support/adhd-assistant

# Re-comment (put `#` back in front of) the `=== macOS Conventional Paths ===`
# lines in .env.

# Restart the bot — it will fall back to the repo-relative defaults.
.venv/bin/python start.py
```

The source tree under the repo is untouched by the migration, so rollback
costs nothing.

## Troubleshooting

### Tilde expansion on the Mac block

A small number of consumers do not call `Path.expanduser()` on the values
they read from `.env`. If the bot appears to create a directory literally
named `~` inside the repo after you uncomment the Mac block, expand the
tilde manually: replace every `~/Library/...` in `.env` with
`/Users/YOUR_USERNAME/Library/...` and restart. You can find your username
by running `echo $USER` in Terminal.

### `gcp-oauth.keys.json` missing on Windows

If you never ran the OAuth flow on Windows, there is nothing to migrate —
the migration script will log "Skip (source missing)" for that entry and
continue. On the Mac, drop the fresh `gcp-oauth.keys.json` you downloaded
from Google Cloud Console straight into
`~/Library/Application Support/adhd-assistant/oauth/gcp-oauth.keys.json`
and set `GOOGLE_OAUTH_CREDENTIALS` in `.env` to that path.

### Re-doing the Google Calendar pickle

On first run of `start.py` on the Mac, syncall will open a browser and
prompt you to authorize. Complete the flow once; the pickle lands at
`~/.gcal_credentials.pickle` and every future run is silent.

### Checking the migration log

```sh
cat "~/Library/Application Support/adhd-assistant/migration_windows_to_mac.log"
```

Each line is of the form `STATUS: SOURCE -> TARGET`. `copied`, `forced_overwrite`,
`skipped_target_exists`, and `skipped_source_missing` are all expected values.
