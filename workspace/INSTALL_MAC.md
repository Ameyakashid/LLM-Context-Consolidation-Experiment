# INSTALL_MAC.md — one-shot install on a fresh Mac

This is the step-by-step guide for putting the ADHD assistant on a Mac Air M2.
Every instruction is copy-paste from Terminal. You do not need to understand
what each command does; you just need to run them in order.

## Before you start

Install **Homebrew** first. Open Terminal and paste:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the on-screen prompts. When it finishes, close Terminal and reopen it
so your shell picks up the new `brew` command.

## Install

1. Open Terminal and `cd` into the repo folder:

   ```sh
   cd ~/adhd-assistant
   ```

   (Change `~/adhd-assistant` to wherever you copied the repo.)

2. Run the installer:

   ```sh
   bash install_mac.sh
   ```

   This installs Python 3.11, Node.js, Taskwarrior, Git, ffmpeg, every Python
   dependency, MagicMirror² + its three modules, and the Google Calendar MCP
   server. Expect 5–15 minutes depending on your network. It is safe to
   interrupt and re-run — every step resumes cleanly.

3. Copy the secrets template:

   ```sh
   cp .env.example .env
   ```

4. Open `.env` in TextEdit (or any editor) and fill in these three values:

   - `OPENROUTER_API_KEY` — sign up at https://openrouter.ai and create a key.
   - `TELEGRAM_BOT_TOKEN` — message `@BotFather` on Telegram, run `/newbot`,
     copy the token it gives you.
   - `TELEGRAM_USER_ID` — message `@userinfobot` on Telegram; it replies with
     your numeric ID.

5. Deploy the workspace to `~/.nanobot/`:

   ```sh
   .venv/bin/python setup_workspace.py
   ```

6. Start the bot and watch it connect:

   ```sh
   .venv/bin/python start.py
   ```

   When you see the Telegram connection banner with no tracebacks, you are
   live. Press Ctrl-C to stop. At this point you can message your Telegram
   bot and get a reply.

7. (Optional, once sub-task 18-04 lands) make the bot start at login:

   ```sh
   bash scripts/install_launchagent.sh
   ```

## Troubleshooting

### `brew: command not found`

Homebrew did not finish installing, or your shell has not picked up its PATH
yet. Close Terminal, reopen it, and try again. If that does not fix it:

- On Apple Silicon, run `eval "$(/opt/homebrew/bin/brew shellenv)"`.
- On Intel Macs, run `eval "$(/usr/local/bin/brew shellenv)"`.

Then re-run `bash install_mac.sh`.

### First `task` command prompts to create `~/.taskrc`

A fresh Taskwarrior install asks to create its config file on first use. If
you hit a `(yes)` prompt, type `yes` and press Enter. This only happens once.

### `npm install` fails with "requires Node.js >= 22"

You have an older Node from somewhere other than Homebrew. Remove it, then:

```sh
brew install node
```

and re-run `bash install_mac.sh`.

### Re-running

`install_mac.sh` is safe to re-run. If a step fails (usually a network
hiccup), fix the cause and run the same command again.
