# LAUNCHAGENT.md — make the bot auto-start at login on macOS

A LaunchAgent is Apple's way of running a per-user background process.
macOS's `launchd` handles the launching, restarting-on-crash, and logging
— all you do is register a plist file under `~/Library/LaunchAgents/`.

You only set this up **once**. After that, the bot runs at every login
and relaunches automatically if it crashes.

## What the LaunchAgent does for you

- Starts `.venv/bin/python start.py` at login.
- Relaunches the bot if it crashes (but NOT if you stop it manually).
- Writes stdout to `~/Library/Logs/adhd-assistant/bot.out.log`.
- Writes stderr to `~/Library/Logs/adhd-assistant/bot.err.log`.
- Waits at least 30 seconds between respawn attempts — a tight crash
  loop pauses instead of hammering the CPU.

The plist template lives at `deploy/com.adhdassistant.bot.plist.template`
in the repo. The installer renders the placeholders (your repo path,
your home dir, your log dir, your feature flags) and writes the result
to `~/Library/LaunchAgents/com.adhdassistant.bot.plist`.

## Prerequisites

Before you install the LaunchAgent, make sure:

1. `bash install_mac.sh` completed successfully — `.venv/bin/python`
   must exist inside the repo.
2. `.venv/bin/python setup_workspace.py` ran at least once — the bot
   needs `~/.nanobot/workspace/SOUL.md` and the Kokoro TTS models.
3. `.env` is filled in with your tokens. If you want path redirection
   to `~/Library/Application Support/adhd-assistant/` (recommended on
   Mac), uncomment the `=== macOS Conventional Paths ===` block.
4. **No manual `python start.py` is currently running.** The LaunchAgent
   will start a fresh copy; two copies would fight for the Telegram
   long-poll.

## Install (`bash scripts/install_launchagent.sh`)

From the repo root, in Terminal:

```sh
bash scripts/install_launchagent.sh
```

The script:

- Reads `ADHD_LOG_DIR` and `NANOBOT_TIMEZONE` from `.env` (or falls
  back to `<repo>/logs` and `America/New_York`).
- Creates the log directory if missing.
- Renders the plist template with your absolute paths.
- Unloads any prior install (tolerant if none), then loads the fresh
  one with `launchctl load -w`.
- Verifies via `launchctl list | grep com.adhdassistant.bot`.

Re-running the installer is safe — it replaces whatever was loaded.

## Uninstall (`bash scripts/uninstall_launchagent.sh`)

```sh
bash scripts/uninstall_launchagent.sh
```

Stops the bot, unloads the LaunchAgent, and removes the plist. Your
data under `~/Library/Application Support/adhd-assistant/` is untouched
— remove it manually only if you want to wipe check-ins, buffers, and
memory.

After uninstall you can still run the bot by hand:

```sh
.venv/bin/python start.py
```

## Check status (`bash scripts/launchagent_status.sh`)

```sh
bash scripts/launchagent_status.sh
```

Prints whether the LaunchAgent is loaded, the PID and last-exit status
from `launchctl list`, and the last 20 lines of each log file. Exits 0
when the bot is running cleanly, non-zero otherwise.

## Reading logs

```sh
# Errors (most useful when something breaks)
tail -f ~/Library/Logs/adhd-assistant/bot.err.log

# Stdout (what the bot prints during normal operation)
tail -f ~/Library/Logs/adhd-assistant/bot.out.log
```

The `Console.app` that ships with macOS opens these same files if you
prefer a GUI. Search for `com.adhdassistant.bot` in the sidebar.

## Troubleshooting

### Homebrew's Python is not on `PATH`

`launchd` does NOT inherit your Terminal's `PATH`. The installed plist
adds `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`, and `/bin` to
the bot's `PATH`. If a subprocess still fails ("command not found"),
add the missing directory to the `PATH` value inside
`~/Library/LaunchAgents/com.adhdassistant.bot.plist` and reload:

```sh
bash scripts/uninstall_launchagent.sh
# edit the template at deploy/com.adhdassistant.bot.plist.template
bash scripts/install_launchagent.sh
```

### The log directory is unwritable

`launchd` will silently refuse to start the bot if it cannot create
the stdout/stderr files. Check `ls -ld ~/Library/Logs/adhd-assistant/`
— the directory must be owned by your user and writable. Fix with
`chmod -R u+rwX`.

### The bot crashes in a tight loop

`ThrottleInterval=30` caps respawn rate at 30 seconds. Open
`bot.err.log` to read the crash. Common causes on Mac:

- Missing API key — re-check `.env`.
- `.venv` was built with a different Python version — rebuild with
  `rm -rf .venv && bash install_mac.sh`.
- Imports failing because a `pip` dep was installed into the wrong
  venv — confirm `.venv/bin/python -c "import nanobot_ai"` succeeds.

### The feature flags I set in `.env` seem to be ignored

The installer bakes a whitelist of feature-flag values from `.env`
into the plist. If you change `.env` after installing, **re-run
`bash scripts/install_launchagent.sh`** to pick up the new values.
Secrets (`OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_USER_ID`) are deliberately NOT baked into the plist — they
live in `~/.nanobot/config.json`, which nanobot reads itself.

## Rollback

### Quick rollback: stop auto-start, keep data

```sh
bash scripts/uninstall_launchagent.sh
```

Then run `.venv/bin/python start.py` by hand whenever you want the bot
up.

### Last-resort rollback: abandon Mac, return to Windows

1. `bash scripts/uninstall_launchagent.sh`
2. Migrate the Mac data back to the repo:
   ```sh
   rsync -a "~/Library/Application Support/adhd-assistant/data/" \
     workspace/data/
   ```
3. Zip the repo, copy to the Windows machine, unzip in the same
   location. Re-comment the `=== macOS Conventional Paths ===` block in
   `.env`. Run `.venv/Scripts/python.exe start.py`.

Data loss: none, as long as you did the rsync before you wiped the Mac.
