#!/usr/bin/env bash
set -euo pipefail

# Codex cloud setup hook for repository tooling and publishing guidance.
# Configure the Codex environment Setup script to run:
#   bash .codex/setup.sh

codex_home="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$codex_home"

if [ -s "$codex_home/AGENTS.override.md" ]; then
  global_agents="$codex_home/AGENTS.override.md"
else
  global_agents="$codex_home/AGENTS.md"
fi

policy_marker="# BEGIN PRODKIT GITHUB PUBLISHING POLICY"
if [ ! -f "$global_agents" ] || ! grep -Fq "$policy_marker" "$global_agents"; then
  if [ -s "$global_agents" ]; then
    printf '\n' >> "$global_agents"
  fi
  cat >> "$global_agents" <<'EOF'
# BEGIN PRODKIT GITHUB PUBLISHING POLICY
## ProdKit GitHub publishing

- Treat GitHub CLI (`gh`) as optional tooling, not a delivery blocker.
- For work that is expected to publish, check Git/GitHub capabilities near the start rather than after implementation is complete.
- Use `git` for branch creation, commits, and pushes. Prefer the available Codex/GitHub integration for pull-request creation and updates.
- Use `gh` only when it is installed and authenticated and the needed operation is not already covered by the GitHub integration.
- If `gh` is missing or unauthenticated, do not stop solely for that reason; continue with `git` and hand off PR creation through the Codex/GitHub integration.
- Never persist personal access tokens, setup-only secrets, private keys, or GitHub credentials into repository files or agent-readable configuration.
- Do not run interactive `gh auth login` in Codex cloud or CI.
# END PRODKIT GITHUB PUBLISHING POLICY
EOF
fi

echo "ProdKit Codex publishing guidance ready: $global_agents"

if command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI already available: $(gh --version | head -n 1)"
else
  can_install=false
  SUDO=()

  if command -v apt-get >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then
      can_install=true
    elif command -v sudo >/dev/null 2>&1; then
      SUDO=(sudo)
      can_install=true
    fi
  fi

  if [ "$can_install" = true ]; then
    echo "Installing GitHub CLI for Codex cloud..."
    if "${SUDO[@]}" apt-get update && "${SUDO[@]}" apt-get install -y gh; then
      echo "GitHub CLI installation completed."
    else
      echo "WARNING: GitHub CLI installation failed; GitHub integration remains the PR path." >&2
    fi
  else
    echo "WARNING: gh is missing and cannot be installed here; GitHub integration remains the PR path." >&2
  fi
fi

if command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI ready: $(gh --version | head -n 1)"
  if gh auth status >/dev/null 2>&1; then
    echo "GitHub CLI authentication is available."
  else
    echo "GitHub CLI is not authenticated; use Codex/GitHub integration for PR creation."
  fi
fi
