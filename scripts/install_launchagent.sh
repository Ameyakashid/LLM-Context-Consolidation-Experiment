#!/usr/bin/env bash
#
# install_launchagent.sh — register the bot as a macOS LaunchAgent.
# Installs to ~/Library/LaunchAgents/com.adhdassistant.bot.plist.
# Idempotent; runs as the invoking user (no admin prompt).

set -euo pipefail

trap 'echo "install_launchagent.sh failed on line ${LINENO}" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TEMPLATE_PATH="${REPO_ROOT}/deploy/com.adhdassistant.bot.plist.template"
LAUNCHAGENTS_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${LAUNCHAGENTS_DIR}/com.adhdassistant.bot.plist"
ENV_FILE="${REPO_ROOT}/.env"

if [[ ! -f "${TEMPLATE_PATH}" ]]; then
  echo "ERROR: template missing at ${TEMPLATE_PATH}" >&2
  exit 1
fi

# ------------------------------------------------------ Read .env (tolerant)
#
# .env may be absent on a fresh clone. grep+cut ignores commented lines, so
# the Mac block staying commented falls through to the $REPO_ROOT/logs
# fallback — matching magicmirror_launcher._resolve_log_dir semantics.

read_env_value() {
  local key="$1"
  if [[ ! -f "${ENV_FILE}" ]]; then
    return 0
  fi
  # `|| true` tolerates grep's exit 1 when the key is absent under pipefail.
  grep -E "^${key}=" "${ENV_FILE}" | tail -n 1 | cut -d= -f2- || true
}

expand_tilde() {
  # Bash 3.2-safe prefix replacement — matches Path.expanduser() for a
  # leading `~`. launchd itself does NOT expand `~` in plist paths.
  local value="$1"
  echo "${value/#\~/$HOME}"
}

ADHD_LOG_DIR="$(read_env_value ADHD_LOG_DIR)"
ADHD_LOG_DIR="$(expand_tilde "${ADHD_LOG_DIR}")"
if [[ -z "${ADHD_LOG_DIR}" ]]; then
  ADHD_LOG_DIR="${REPO_ROOT}/logs"
fi

NANOBOT_TIMEZONE="$(read_env_value NANOBOT_TIMEZONE)"
if [[ -z "${NANOBOT_TIMEZONE}" ]]; then
  NANOBOT_TIMEZONE="America/New_York"
fi

mkdir -p "${ADHD_LOG_DIR}"
mkdir -p "${LAUNCHAGENTS_DIR}"

# ---------------------------------------------- Build EXTRA_ENV_ENTRIES
#
# Whitelist: boolean feature flags + path/cron overrides that start.py
# and its spawned children read at runtime. API keys and tokens are NOT
# included — they live in ~/.nanobot/config.json, which nanobot reads
# itself. The plist is world-readable under ~/Library/LaunchAgents/,
# so keep the whitelist secret-free forever.

PLIST_ENV_WHITELIST=(
  PULSE_ENGINE_ENABLED
  DREAM_STATE_ENABLED
  DREAM_STATE_CRON
  VOICE_AUTO_ENABLED
  VOICE_DISCO_ENABLED
  GOOGLE_CALENDAR_ENABLED
  MAGICMIRROR_ENABLED
  MAGICMIRROR_AUTOSTART_ENABLED
  TASKWARRIOR_ENABLED
  SYNCALL_ENABLED
  ADHD_DATA_DIR
  DASHBOARD_DATA_DIR
  TASKWARRIOR_DATA_DIR
)

xml_escape() {
  local value="$1"
  value="${value//&/&amp;}"
  value="${value//</&lt;}"
  value="${value//>/&gt;}"
  echo "${value}"
}

EXTRA_ENTRIES_FILE="$(mktemp "${TMPDIR:-/tmp}/adhd_plist_extra.XXXXXX")"
trap 'rm -f "${EXTRA_ENTRIES_FILE}"' EXIT

for key in "${PLIST_ENV_WHITELIST[@]}"; do
  raw="$(read_env_value "${key}")"
  if [[ -z "${raw}" ]]; then
    continue
  fi
  expanded="$(expand_tilde "${raw}")"
  escaped="$(xml_escape "${expanded}")"
  printf '    <key>%s</key><string>%s</string>\n' "${key}" "${escaped}" \
    >> "${EXTRA_ENTRIES_FILE}"
done

# ---------------------------------------------------------- Render plist
#
# Two-pass substitution: sed handles single-line placeholders; the
# EXTRA_ENV_ENTRIES line is replaced by the contents of the temp file.

sed \
  -e "s|\${REPO_ROOT}|${REPO_ROOT}|g" \
  -e "s|\${HOME}|${HOME}|g" \
  -e "s|\${ADHD_LOG_DIR}|${ADHD_LOG_DIR}|g" \
  -e "s|\${NANOBOT_TIMEZONE}|${NANOBOT_TIMEZONE}|g" \
  -e "/\${EXTRA_ENV_ENTRIES}/r ${EXTRA_ENTRIES_FILE}" \
  -e "/\${EXTRA_ENV_ENTRIES}/d" \
  "${TEMPLATE_PATH}" > "${TARGET_PLIST}"

# ----------------------------------------------------------- (Re)load
#
# Unload first to tolerate a prior install; `|| true` keeps set -e from
# tripping when no prior plist is registered.

launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
launchctl load -w "${TARGET_PLIST}"

# -------------------------------------------------------------- Verify

if launchctl list | grep -q "com.adhdassistant.bot"; then
  echo "LaunchAgent loaded: com.adhdassistant.bot"
else
  echo "ERROR: launchctl list did not report com.adhdassistant.bot" >&2
  exit 1
fi

cat <<MSG

=== LaunchAgent installed ===

Plist:    ${TARGET_PLIST}
Logs:     ${ADHD_LOG_DIR}/bot.out.log
          ${ADHD_LOG_DIR}/bot.err.log
Status:   bash scripts/launchagent_status.sh
Stop:     bash scripts/uninstall_launchagent.sh

The bot will auto-start at every login and relaunch on crash.
MSG
