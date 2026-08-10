#!/usr/bin/env bash
set -euo pipefail

# Codex cloud setup hook for repository tooling.
# Run this from the Codex environment Setup script as:
#   bash .codex/setup.sh

if command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI already available: $(gh --version | head -n 1)"
  exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "ERROR: gh is missing and this environment does not provide apt-get." >&2
  exit 1
fi

if [ "$(id -u)" -eq 0 ]; then
  SUDO=()
elif command -v sudo >/dev/null 2>&1; then
  SUDO=(sudo)
else
  echo "ERROR: gh is missing and package installation requires root or sudo." >&2
  exit 1
fi

echo "Installing GitHub CLI for Codex cloud..."
"${SUDO[@]}" apt-get update
"${SUDO[@]}" apt-get install -y gh

echo "GitHub CLI ready: $(gh --version | head -n 1)"

if gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI authentication is available."
else
  echo "GitHub CLI is installed but not authenticated; use Codex/GitHub integration for PR creation when needed."
fi
