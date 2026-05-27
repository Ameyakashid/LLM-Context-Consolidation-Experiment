#!/usr/bin/env bash
#
# install_mac.sh — one-shot Mac installer for the ADHD assistant.
#
# Run from a fresh Mac after Homebrew is installed:
#   bash install_mac.sh
# Idempotent. Every step skips when already satisfied.

set -euo pipefail

cd "$(dirname "$0")"

CURRENT_PHASE="startup"
trap 'echo "FAILED in phase: ${CURRENT_PHASE}" >&2' ERR

phase() {
  CURRENT_PHASE="$1"
  echo ""
  echo "=== $1 ==="
}

# ---------------------------------------------------------------- Homebrew

phase "[0/7] Homebrew presence check"

if ! command -v brew >/dev/null 2>&1; then
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  else
    echo "Homebrew not found. Install it from https://brew.sh first, then re-run." >&2
    exit 1
  fi
fi

ARCH="$(uname -m)"
if [[ "${ARCH}" == "arm64" ]]; then
  echo "Apple Silicon detected — native ARM64 builds will be used."
else
  echo "Architecture: ${ARCH} (Intel Mac or emulated)."
fi

# ----------------------------------------------------- [1/7] Brew packages

phase "[1/7] Homebrew packages"

BREW_PACKAGES=(python@3.13 expat node task git ffmpeg)
for pkg in "${BREW_PACKAGES[@]}"; do
  brew list "${pkg}" >/dev/null 2>&1 || brew install "${pkg}"
done

# ---------------------------------------------------------- [2/7] venv

phase "[2/7] Python virtualenv"

export DYLD_LIBRARY_PATH="/opt/homebrew/opt/expat/lib:${DYLD_LIBRARY_PATH:-}"

if [[ -d .venv ]]; then
  echo ".venv already present — reusing."
else
  python3.13 -m venv .venv
fi

# Persist the libexpat workaround into the venv so every future activation gets it.
ACTIVATE=".venv/bin/activate"
if ! grep -q "DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib" "${ACTIVATE}"; then
  cat >> "${ACTIVATE}" <<'PATCH'

# macOS Tahoe workaround: brewed Python's pyexpat is linked against a newer
# libexpat than /usr/lib ships. Force brew's expat onto the dyld search path.
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/expat/lib:${DYLD_LIBRARY_PATH:-}"
PATCH
fi

# ------------------------------------------------- [3/7] Python dependencies

phase "[3/7] Python dependencies"

.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-dev.txt

# -------------------------------------------- [4/7] Google Calendar MCP

phase "[4/7] Google Calendar MCP server"

(cd mcp/google-calendar && npm install && npm run build)

# ------------------------------------------------ [5/7] MagicMirror core

phase "[5/7] MagicMirror core"

# --ignore-scripts defuses the upstream postinstall `git clean -df` that
# explodes in a non-git vendor drop. Matches magicmirror_setup.py.
(cd magicmirror && npm install --ignore-scripts)

# --------------------------------------------- [6/7] MagicMirror modules

phase "[6/7] MagicMirror modules"

for module_dir in magicmirror/modules/MMM-*; do
  [[ -f "${module_dir}/package.json" ]] || continue
  echo "Installing $(basename "${module_dir}")"
  (cd "${module_dir}" && npm install)
done

# --------------------------------------------------------------- [7/7] Done

phase "[7/7] Finish"

CURRENT_PHASE="complete"

cat <<'MSG'

=== Install complete ===

Next steps:
  1. Copy the secrets template:
       cp .env.example .env
  2. Open .env in a text editor and fill in:
       OPENROUTER_API_KEY
       TELEGRAM_BOT_TOKEN
       TELEGRAM_USER_ID
  3. Deploy the workspace to ~/.nanobot/:
       .venv/bin/python setup_workspace.py
  4. Start the bot:
       .venv/bin/python start.py

The full user guide lives at workspace/INSTALL_MAC.md.
MSG
