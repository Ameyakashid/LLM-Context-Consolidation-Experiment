# Taskwarrior — Canonical task ledger

## TL;DR

Taskwarrior is the command-line task manager your bot uses as its
canonical ledger once `TASKWARRIOR_ENABLED=true`. It replaces the legacy
`workspace/data/tasks.json` file with a battle-tested CLI-backed store at
`workspace/data/taskwarrior/`. Flag it on, run the one-shot migration
script, restart the bot. Every tool, hook, and dashboard endpoint picks
up the new backend automatically.

## Why

Three reasons the bot moved off the JSON file for Phase 2:

1. **Bidirectional Google Calendar sync.** The syncall daemon reads and
   writes Taskwarrior; it has no adapter for a homemade JSON store.
2. **A real ledger.** Taskwarrior tracks annotations, start/stop, tag
   history, and dependencies out of the box. JSON did none of this.
3. **Standard `task` CLI.** You can inspect or edit the same store from a
   terminal without touching the bot.

The bot still ships the JSON backend as a fallback — set the flag off
and restart to revert any time.

## Prerequisites

Install Taskwarrior and put `task` on your PATH:

- **macOS:** `brew install task`
- **Windows:** `choco install task`
- **Debian/Ubuntu:** `apt install taskwarrior`
- **Fedora:** `dnf install task`

Verify: `task --version` prints `2.x.x` or later.

## First-time setup

1. Install Taskwarrior (above) and confirm `task --version` works.
2. Set `TASKWARRIOR_ENABLED=true` in your `.env`.
3. Run `python scripts/migrate_json_to_taskwarrior.py` once. It reads
   `workspace/data/tasks.json`, writes each row into Taskwarrior at
   `workspace/data/taskwarrior/`, and tags each imported row with a
   `migrated_<hex>` tag so you can find them later. The source JSON is
   not modified.
4. Run `python setup_workspace.py` (if you did not already).
5. Start the bot: `python start.py`. Every consumer — the LLM task
   tools, the dashboard `/tasks` endpoint, the MagicMirror `tasks.md`
   feed — now reads and writes Taskwarrior transparently.

## Operation

Data lives under `workspace/data/taskwarrior/` by default, with files
`pending.data`, `completed.data`, `undo.data`, and `backlog.data`.
Override with `TASKWARRIOR_DATA_DIR=/absolute/path` in `.env` if you
want it elsewhere.

To inspect the store from a terminal, point the `task` CLI at the same
directory:

```
TASKDATA=workspace/data/taskwarrior task list
TASKDATA=workspace/data/taskwarrior task 1 info
```

The bot uses tasklib internally (a Python wrapper around `task`), so
everything the CLI does the bot can do and vice versa.

## Migration script

`scripts/migrate_json_to_taskwarrior.py` turns a JSON ledger into a
Taskwarrior one. Common flags:

- `--dry-run` — read the JSON, plan the imports, print what would
  happen. No writes.
- `--force` — re-import even when the Taskwarrior data dir already has
  rows. Useful after a rollback where you want Taskwarrior to match the
  JSON state.
- `--json-path <path>` — override the source JSON location (defaults to
  `workspace/data/tasks.json`).
- `--taskwarrior-dir <path>` — override the target data dir (defaults
  to `workspace/data/taskwarrior/`).

A per-task run log is written to
`<data-dir>/taskwarrior_migration.log`. Exit codes: `0` success,
`2` missing source, `3` precondition failure, `4` partial import.
Re-running without `--force` is a no-op once the target has rows.

## Rollback

Three steps:

1. Set `TASKWARRIOR_ENABLED=false` in `.env` (or remove the line).
2. Restart the bot (`python start.py`).
3. Verify: the dashboard `/tasks` endpoint serves from
   `workspace/data/tasks.json` again.

**Divergence warning.** Tasks you created while Taskwarrior was
canonical live only in `workspace/data/taskwarrior/`. The JSON backend
cannot see them. If you flip the flag back on later, Taskwarrior still
has its rows and the JSON file still has its own — the two sets have
drifted. Pick one as authoritative and re-run the migration with
`--force` from the other side, or accept the drift. **Do not
flip-flop the flag.** Pick a backend and stay there.

## Interaction with syncall

Syncall is the bidirectional Taskwarrior ↔ Google Calendar daemon. It
is gated separately by `SYNCALL_ENABLED=true` and reads/writes the same
Taskwarrior data dir the bot uses. Syncall is not needed for
Taskwarrior to work; it is an opt-in layer on top. See
`SYNCALL.md` for OAuth, filters, and the one-time interactive consent.

## Troubleshooting

**`RuntimeError: Taskwarrior CLI ('task') not found on PATH`** — the
flag is on but the binary is missing. Install it with the command
above for your OS, then restart the bot.

**The dashboard shows an empty task list after I migrated.** You
probably started the bot with `TASKWARRIOR_ENABLED=true` before running
the migration. Stop the bot, run `python scripts/migrate_json_to_taskwarrior.py`,
start it again.

**Tasks show as "in progress" when I expected "pending".** The bot
maps `in_progress` to a synthetic `+started` tag on top of
Taskwarrior's `pending` status. If you see surprising `+started` tags,
it is because the task was once `in_progress`. Remove the tag with
`task <id> modify -started`.

**`workspace/data/tasks.json exists but Taskwarrior data dir is empty`
warning at setup.** The migration has not run yet. Run the migration
script before you start the bot, or the bot will serve an empty ledger
from Taskwarrior while the JSON still holds your old rows.

**Permission errors on `workspace/data/taskwarrior/`.** Make sure the
user running the bot can read and write the directory. On Windows,
verify the path is not under a OneDrive-synced folder that locks files.
