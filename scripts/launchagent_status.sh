#!/usr/bin/env bash
#
# launchagent_status.sh — report load state, last exit status, and log
# tails for the ADHD bot LaunchAgent. Exit 0 when loaded cleanly;
# non-zero otherwise.

set -euo pipefail

trap 'echo "launchagent_status.sh failed on line ${LINENO}" >&2' ERR

LABEL="com.adhdassistant.bot"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

ADHD_LOG_DIR=""
if [[ -f "${ENV_FILE}" ]]; then
  ADHD_LOG_DIR="$(grep -E '^ADHD_LOG_DIR=' "${ENV_FILE}" | tail -n 1 | cut -d= -f2- || true)"
  ADHD_LOG_DIR="${ADHD_LOG_DIR/#\~/$HOME}"
fi
if [[ -z "${ADHD_LOG_DIR}" ]]; then
  ADHD_LOG_DIR="${REPO_ROOT}/logs"
fi

STATUS_LINE="$(launchctl list | grep "${LABEL}" || true)"
if [[ -z "${STATUS_LINE}" ]]; then
  echo "LaunchAgent ${LABEL} is NOT loaded."
  echo "Install with: bash scripts/install_launchagent.sh"
  exit 1
fi

echo "LaunchAgent ${LABEL} is loaded:"
echo "  ${STATUS_LINE}"
echo ""
echo "--- bot.out.log (last 20 lines) ---"
tail -n 20 "${ADHD_LOG_DIR}/bot.out.log" 2>/dev/null || echo "(no stdout log yet)"
echo ""
echo "--- bot.err.log (last 20 lines) ---"
tail -n 20 "${ADHD_LOG_DIR}/bot.err.log" 2>/dev/null || echo "(no stderr log yet)"

pid="$(awk '{print $1}' <<< "${STATUS_LINE}")"
last_exit="$(awk '{print $2}' <<< "${STATUS_LINE}")"
if [[ "${pid}" != "-" ]] || [[ "${last_exit}" == "0" ]]; then
  exit 0
fi
exit 1
