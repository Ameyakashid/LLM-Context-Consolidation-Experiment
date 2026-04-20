# Mac Deployment Runbook

The ADHD Assistant's permanent home is a Mac Air M2. This runbook is for
the single user who owns the device and wants the bot running 24/7.
Windows is dev-only from Task 18 forward.

## TL;DR — Five Commands

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
bash install_mac.sh
cp .env.example .env && "$EDITOR" .env
python scripts/migrate_windows_to_mac.py --apply
bash scripts/install_launchagent.sh
```

After the fifth command the bot is running and will relaunch automatically
after logout, reboot, or an unclean crash.

## First-time setup

1. **Homebrew.** The first command installs it. Already have Homebrew?
   Skip ahead.
2. **System dependencies + venv.** `bash install_mac.sh` installs
   `python@3.12`, `node`, `taskwarrior`, `uv`, creates `.venv/`, installs
   Python and npm dependencies, and downloads the Kokoro TTS models.
   Rerunnable — it skips steps already done. Companion:
   [`INSTALL_MAC.md`](INSTALL_MAC.md).
3. **Credentials.** `cp .env.example .env` then edit. Three keys are
   required (`OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_USER_ID`). The Mac path block near the bottom of
   `.env.example` shows the `~/Library/...` defaults; leave them
   commented unless you want non-default storage.
4. **Data migration (if coming from Windows).**
   `python scripts/migrate_windows_to_mac.py --dry-run` prints the plan;
   `--apply` performs it. Rerunning `--apply` is idempotent — already-moved
   files are skipped, not overwritten. Companion:
   [`MAC_PATHS.md`](MAC_PATHS.md).
5. **Workspace deploy.** `python setup_workspace.py` copies workspace
   templates into `~/.nanobot/workspace/` and resolves `config.json`.
   Required once before the first `start.py` or LaunchAgent run.
6. **LaunchAgent install.** `bash scripts/install_launchagent.sh` writes
   `~/Library/LaunchAgents/com.adhdassistant.bot.plist`, runs
   `launchctl load -w`, and verifies with `launchctl list`. Rerunning
   is safe — it unloads before loading. Companion:
   [`LAUNCHAGENT.md`](LAUNCHAGENT.md).

## Verifying the install

Within ~5 seconds of starting you should see, in
`~/Library/Logs/adhd-assistant/bot.out.log`:

```
gateway_runner INFO Starting custom gateway on port 18790
custom_gateway INFO DiscoHook loaded from ...workspace/disco_voices.yaml
task_tools INFO Registered 5 task tools: create, list, get, update, complete
dashboard_api INFO Dashboard API listening on 0.0.0.0:8085
nanobot.channels.manager INFO Telegram channel enabled
gateway_runner INFO Custom gateway ready: 6 hooks
Cron service started with 12 jobs
Heartbeat started (every 1800s)
```

- Dashboard: open `http://<mac-LAN-ip>:8085` on the Fire Tablet's Silk
  browser. The cognitive-state banner should render within 2 seconds.
- MagicMirror (if enabled): `pgrep -f magicmirror` returns a PID;
  the tablet renders the configured modules.
- LaunchAgent: `bash scripts/launchagent_status.sh` prints the PID
  and tails the last 20 log lines.

## Starting / stopping / restarting

```bash
launchctl kickstart -k gui/$(id -u)/com.adhdassistant.bot   # restart
launchctl unload ~/Library/LaunchAgents/com.adhdassistant.bot.plist   # stop
launchctl load -w ~/Library/LaunchAgents/com.adhdassistant.bot.plist  # start
```

The `-k` flag in `kickstart` kills the running process first — use it
when you've edited `.env` or `config.json` and want the bot to pick up
the new value.

Want to run it manually for debugging? Unload the LaunchAgent (so it
doesn't fight you), activate the venv, and run `python start.py`
directly from the repo root. Ctrl+C stops it cleanly within ~15 s.

## Where things live on Mac

| Thing | Path |
|-------|------|
| Repo (code) | wherever you cloned it |
| venv | `<repo>/.venv/` |
| App data (tasks, buffers, memories, checkins) | `~/Library/Application Support/adhd-assistant/data/` |
| Logs | `~/Library/Logs/adhd-assistant/` (`bot.out.log`, `bot.err.log`, `magicmirror.log`) |
| LaunchAgent plist | `~/Library/LaunchAgents/com.adhdassistant.bot.plist` |
| Nanobot workspace (SOUL, HEARTBEAT, state.yaml) | `~/.nanobot/workspace/` |
| Config | `~/.nanobot/config.json` |
| Kokoro TTS models | `~/.nanobot/models/kokoro/` |
| Google Calendar OAuth token | `~/.gcal_credentials.pickle` (hardcoded in the vendored syncall — not configurable) |

Override `ADHD_DATA_DIR` or `DASHBOARD_DATA_DIR` in `.env` if you want
a different data root; both expand `~` automatically.

## Troubleshooting

- **`.env` missing** → `setup_workspace.py` refuses to run. Copy the
  example and fill the three required keys.
- **OAuth expired** → `~/.gcal_credentials.pickle` is stale. Delete it,
  re-run `python scripts/setup_gcal_oauth.py`, re-trigger the
  LaunchAgent with `launchctl kickstart -k`.
- **Taskwarrior CLI not on PATH from the LaunchAgent** → the plist
  `PATH` includes `/opt/homebrew/bin` for Apple Silicon Homebrew. If
  you installed `task` somewhere else, edit the plist's
  `EnvironmentVariables.PATH` and reload the agent.
- **MagicMirror port clash** → `config/config.js` `port` defaults to
  8080. Change it in `.env` via `MAGICMIRROR_PORT=8090`, re-run
  `setup_workspace.py`, restart.
- **Dashboard port clash** → `DASHBOARD_PORT=8086` in `.env`, restart.

If costs drift, check [`workspace/TEMM1E_PULSE.md`](TEMM1E_PULSE.md) —
the Pulse + Dream pair is the only LLM-priced feature on a typical day.
The $7/month ceiling assumes `PULSE_ENGINE_ENABLED=true` and
`DREAM_STATE_ENABLED=true`. Turning them off drops monthly cost to the
heartbeat-only floor (~$0.50).

## Rollback

Abandoning the Mac deployment? The reverse of the TL;DR:

```bash
bash scripts/uninstall_launchagent.sh
python scripts/migrate_windows_to_mac.py --reverse --apply
```

`uninstall_launchagent.sh` unloads the agent and removes the plist — no
residue. `migrate_windows_to_mac.py --reverse --apply` copies the data
directories back to repo-local paths (matches the Windows layout);
rerunning it is idempotent. After that, zip the repo and move it back.

## Cost posture

| Feature flag | Monthly cost added |
|--------------|--------------------|
| Baseline (heartbeat only) | ~$0.50 |
| `PULSE_ENGINE_ENABLED=true` | ~$2 (four check-ins/day) |
| `DREAM_STATE_ENABLED=true` | ~$4 (one 3AM run/day) |
| All other flags | $0 (local or free-tier only) |

Total ceiling: $7/month on OpenRouter with
`x-ai/grok-4.1-fast` (active model per user's preference).
