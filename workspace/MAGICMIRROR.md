# MagicMirror — Fire Tablet Display Setup

This file is for you, the human. It explains how the Fire Tablet display works, how to turn it on, how to point the tablet at it, and how to turn it off.

## TL;DR

1. Put `MAGICMIRROR_ENABLED=true` in your `.env`.
2. Run `python setup_workspace.py`. It installs MagicMirror² and three modules, then renders `magicmirror/config/config.js`.
3. Start the mirror server: `cd magicmirror && npm run server`.
4. Open the Silk browser on the Fire tablet at `http://<pc-lan-ip>:8080/` and swipe through three pages: **Tasks**, **State + Buffers**, **Schedule**. Alerts appear as toasts.
5. Heartbeats now dispatch webhooks to the tablet and rewrite the three feed files. That's it.

If something breaks, skim *"When It Breaks"* below. Usually it's the wrong LAN IP or a stale IP whitelist.

---

## What This Does

Two things, separately:

**1. Webhook alerts on the tablet.** When your cognitive state changes, a buffer drops to its threshold, or a scheduled check-in is missed, the agent POSTs a small JSON body to MagicMirror's webhook endpoint. MMM-WebHookAlerts renders a toast on the mirror using the template that matches `templateName` (`state_change`, `buffer_alert`, `missed_checkin`).

**2. Three auto-refreshing pages.** Each heartbeat the agent rewrites three markdown files in `magicmirror/modules/MMM-Markdown/markdown/`:
- `tasks.md` — active / completed-today / blocked tasks
- `state_buffers.md` — current cognitive state + active buffers
- `schedule.md` — enabled check-ins with next-due or overdue hints

MMM-Markdown reads them; MMM-pages binds them to three swipe pages.

Everything is **read-only from the tablet's perspective**. The tablet is a display, not an input device.

## What This Doesn't Do

- No writes from the tablet. No buttons, no forms, no "complete task" actions.
- No external network. MagicMirror binds to your LAN only; the webhook sender refuses anything that isn't a loopback address (`127.0.0.1` / `localhost` / `::1`).
- No polling in the background. Alerts fire from the heartbeat tick; feeds refresh on the same tick.
- No replay on restart. Dedup state is in-memory — after a restart you may see one duplicate alert. That's the accepted tradeoff.

## First-Time Setup

You need Node.js ≥22.21.1 and npm on your PATH. Verify: `node --version && npm --version`.

1. Set `MAGICMIRROR_ENABLED=true` (and optionally `MAGICMIRROR_HOST`, `MAGICMIRROR_PORT`, `MAGICMIRROR_IP_WHITELIST_JSON`) in your `.env`.
2. Run `python setup_workspace.py`. Setup:
   - installs MagicMirror² core under `magicmirror/` with `--ignore-scripts`
   - installs the three vendored modules (MMM-WebHookAlerts, MMM-Markdown, MMM-pages)
   - renders `magicmirror/config/config.js` from the template with your env values
3. Start the mirror: `cd magicmirror && npm run server`.
4. On the Fire tablet, open Silk and navigate to `http://<your-pc-lan-ip>:8080/`.
5. Start the bot as usual. Heartbeat ticks now drive both webhooks and feed refreshes.

## Env Vars

| Var | Default | What it does |
|---|---|---|
| `MAGICMIRROR_ENABLED` | `false` | Master switch. Flag-off = zero hook, zero thread pool, zero feed writes. |
| `MAGICMIRROR_WEBHOOK_HOST` | `127.0.0.1` | Host the sender POSTs to. Must be loopback. |
| `MAGICMIRROR_WEBHOOK_PORT` | `8080` | Port the sender POSTs to. Match `MAGICMIRROR_PORT`. |
| `MAGICMIRROR_HOST` | `0.0.0.0` | Host the mirror server binds to. `0.0.0.0` = all LAN interfaces. |
| `MAGICMIRROR_PORT` | `8080` | Port the mirror server listens on. |
| `MAGICMIRROR_IP_WHITELIST_JSON` | LAN ranges | JSON array of IPs/CIDRs the mirror accepts. |

## How Alerts Work

| Alert | Fired when | Dedup window |
|---|---|---|
| `state_change` | `get_cognitive_state()` differs from the last dispatched value | None — every transition fires once |
| `buffer_alert` | buffer at or below `alert_threshold` | Per-day, keyed on buffer name |
| `missed_checkin` | enabled entry past its staleness window, not run today | Per-day, keyed on `type_id` |

All dedup state is in-memory and resets on agent restart.

## Pages and Feeds

Three files under `magicmirror/modules/MMM-Markdown/markdown/` are rewritten atomically each heartbeat:

- `tasks.md` — "Active", "Completed today", "Blocked" sections. Active sorted by due date; blocked by title.
- `state_buffers.md` — current cognitive state heading, then active buffers with level/capacity and a low-marker past threshold.
- `schedule.md` — enabled check-ins sorted by target time. Each line hints the next-due duration, overdue duration, or "missed today, next tomorrow in …".

The `.md` files themselves are gitignored (except `examples.md` shipped by MMM-Markdown).

## When It Breaks

**Tablet can't reach the mirror.** Ping `http://<pc-lan-ip>:8080/` from the Fire's browser. If it times out: (a) make sure the mirror server is running, (b) make sure your firewall allows inbound `8080`, (c) check `MAGICMIRROR_IP_WHITELIST_JSON` includes the tablet's subnet.

**No alerts, feeds updating fine.** The webhook sender quietly refuses non-loopback hosts. Confirm `MAGICMIRROR_WEBHOOK_HOST=127.0.0.1`. Check the agent log for `MagicMirror webhook … URL error` lines.

**No alerts and no feed updates.** The hook only fires during heartbeat sessions. Confirm `HEARTBEAT_ENABLED=true` (or equivalent) and that `is_scheduled_session()` returns True during the heartbeat window.

**Feeds never change.** Look for `MagicMirror hook refresh_feeds failed` in the agent log — it's rate-limited to one WARNING per hour per hook instance. Usually a permissions/disk-full issue on the feed directory.

**One duplicate alert after restart.** Known and accepted. In-memory dedup resets on restart; next tick catches up.

## Turning It Off

Set `MAGICMIRROR_ENABLED=false` in `.env` and restart the agent. The flag-off path builds no hook, starts no thread pool, and writes no files. The vendored `magicmirror/` tree stays on disk but is inert.

## Auto-Launch on Mac

The mirror's `npm start` can be spawned automatically by `start.py` as a supervised child process. This is opt-in: set `MAGICMIRROR_AUTOSTART_ENABLED=true` once you have Node/npm installed and `magicmirror/config/config.js` rendered. Default is `false`.

| Var | Default | What it does |
|---|---|---|
| `MAGICMIRROR_AUTOSTART_ENABLED` | `false` | Master switch for in-process autostart. Independent of `MAGICMIRROR_ENABLED`. |
| `ADHD_LOG_DIR` | unset | When set, `magicmirror.log` and `magicmirror.err` land here instead of `<repo>/logs/`. Tildes are expanded. |

**Shutdown order.** `start.py` stops the mirror child before the syncall daemon so the Fire Tablet disconnects cleanly first. Shutdown sends a terminate signal, waits 10 seconds, then falls back to kill.

**Logs.** By default stdout/stderr go to `<repo>/logs/magicmirror.log` and `<repo>/logs/magicmirror.err` (append mode, UTF-8). If `ADHD_LOG_DIR` is set, logs land there instead. If the target directory is unwritable the launcher warns once and routes output to `DEVNULL` — MagicMirror still runs.

**If autostart is off.** Run the mirror yourself from another terminal: `cd magicmirror && npm run server` (the documented HTTP-server command matching TL;DR step 3 above). The bot will not spawn or reap it.

**If the flag is on but setup hasn't run.** `launch_magicmirror` raises `RuntimeError` pointing at the missing `config.js` with a hint to run `setup_workspace()` first.
