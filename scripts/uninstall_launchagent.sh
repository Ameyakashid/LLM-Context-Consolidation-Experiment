#!/usr/bin/env bash
#
# uninstall_launchagent.sh — stop the ADHD bot LaunchAgent and remove
# its plist. Idempotent: safe to re-run when no plist is installed.

set -euo pipefail

trap 'echo "uninstall_launchagent.sh failed on line ${LINENO}" >&2' ERR

TARGET_PLIST="${HOME}/Library/LaunchAgents/com.adhdassistant.bot.plist"

launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
rm -f "${TARGET_PLIST}"

cat <<'MSG'

=== LaunchAgent uninstalled ===

Data under ~/Library/Application Support/adhd-assistant/ is untouched;
remove it manually if you want to start fresh.

Run manually with: .venv/bin/python start.py
MSG
