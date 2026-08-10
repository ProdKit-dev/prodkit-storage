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

policy_begin="# BEGIN PRODKIT GITHUB PUBLISHING POLICY"
policy_end="# END PRODKIT GITHUB PUBLISHING POLICY"
policy_file="$(mktemp "${TMPDIR:-/tmp}/prodkit-codex-policy.XXXXXX")"
agents_tmp=""
cleanup() {
  rm -f "$policy_file"
  if [ -n "$agents_tmp" ]; then
    rm -f "$agents_tmp"
  fi
}
trap cleanup EXIT

cat > "$policy_file" <<'EOF_POLICY'
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
EOF_POLICY

refresh_policy() {
  local target="$1"
  local begin_count=0
  local end_count=0

  if [ -f "$target" ]; then
    begin_count="$(grep -Fxc "$policy_begin" "$target" || true)"
    end_count="$(grep -Fxc "$policy_end" "$target" || true)"
  fi

  if [ "$begin_count" -gt 0 ] || [ "$end_count" -gt 0 ]; then
    if [ "$begin_count" -eq 0 ] || [ "$end_count" -eq 0 ] || [ "$begin_count" -ne "$end_count" ]; then
      echo "WARNING: malformed ProdKit publishing policy markers in $target; leaving existing instructions unchanged." >&2
      return 0
    fi

    agents_tmp="$(mktemp "${TMPDIR:-/tmp}/prodkit-codex-agents.XXXXXX")"
    awk -v begin="$policy_begin" -v end="$policy_end" -v policy="$policy_file" '
      function emit_policy(line) {
        while ((getline line < policy) > 0) print line
        close(policy)
      }
      $0 == begin {
        if (!emitted) {
          emit_policy()
          emitted = 1
        }
        in_policy = 1
        next
      }
      in_policy && $0 == end {
        in_policy = 0
        next
      }
      !in_policy { print }
    ' "$target" > "$agents_tmp"
    cat "$agents_tmp" > "$target"
    rm -f "$agents_tmp"
    agents_tmp=""
  else
    if [ -s "$target" ]; then
      printf '\n' >> "$target"
    fi
    cat "$policy_file" >> "$target"
  fi
}

refresh_policy "$global_agents"
echo "ProdKit Codex publishing guidance ready: $global_agents"

gh_command="${PRODKIT_CODEX_GH_COMMAND:-gh}"
apt_get_command="${PRODKIT_CODEX_APT_GET_COMMAND:-apt-get}"
sudo_command="${PRODKIT_CODEX_SUDO_COMMAND:-sudo}"
effective_uid="${PRODKIT_CODEX_EFFECTIVE_UID:-$(id -u)}"

if command -v "$gh_command" >/dev/null 2>&1; then
  echo "GitHub CLI already available: $($gh_command --version | head -n 1)"
else
  can_install=false
  SUDO=()

  if command -v "$apt_get_command" >/dev/null 2>&1; then
    if [ "$effective_uid" -eq 0 ]; then
      can_install=true
    elif command -v "$sudo_command" >/dev/null 2>&1; then
      SUDO=("$sudo_command" -n)
      can_install=true
    fi
  fi

  if [ "$can_install" = true ]; then
    echo "Installing GitHub CLI for Codex cloud..."
    if "${SUDO[@]}" "$apt_get_command" update && "${SUDO[@]}" "$apt_get_command" install -y gh; then
      echo "GitHub CLI installation completed."
    else
      echo "WARNING: GitHub CLI installation failed; GitHub integration remains the PR path." >&2
    fi
  else
    echo "WARNING: gh is missing and cannot be installed here; GitHub integration remains the PR path." >&2
  fi
fi

if command -v "$gh_command" >/dev/null 2>&1; then
  echo "GitHub CLI ready: $($gh_command --version | head -n 1)"
  if "$gh_command" auth status >/dev/null 2>&1; then
    echo "GitHub CLI authentication is available."
  else
    echo "GitHub CLI is not authenticated; use Codex/GitHub integration for PR creation."
  fi
fi
