#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
setup_script="${PRODKIT_SETUP_SCRIPT:-$repo_root/.codex/setup.sh}"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_contains() {
  local file="$1"
  local text="$2"
  grep -Fq -- "$text" "$file" || fail "$file does not contain: $text"
}

assert_not_contains() {
  local file="$1"
  local text="$2"
  if grep -Fq -- "$text" "$file"; then
    fail "$file unexpectedly contains: $text"
  fi
}

run_setup() {
  local codex_home="$1"
  shift
  CODEX_HOME="$codex_home" \
    PRODKIT_CODEX_GH_COMMAND="prodkit-missing-gh" \
    PRODKIT_CODEX_APT_GET_COMMAND="prodkit-missing-apt-get" \
    "$@" \
    bash "$setup_script"
}

tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/prodkit-codex-test.XXXXXX")"
trap 'rm -rf "$tmp_root"' EXIT

# Existing policy blocks are upgraded in place, surrounding instructions survive,
# and repeated setup runs are byte-for-byte idempotent.
upgrade_home="$tmp_root/upgrade"
mkdir -p "$upgrade_home"
cat > "$upgrade_home/AGENTS.md" <<'EOF_AGENTS'
# Existing global guidance
Keep this before the managed block.

# BEGIN PRODKIT GITHUB PUBLISHING POLICY
stale policy text
# END PRODKIT GITHUB PUBLISHING POLICY

Keep this after the managed block.
EOF_AGENTS
run_setup "$upgrade_home" >/dev/null 2>&1
assert_contains "$upgrade_home/AGENTS.md" "Treat GitHub CLI (\`gh\`) as optional tooling"
assert_not_contains "$upgrade_home/AGENTS.md" "stale policy text"
assert_contains "$upgrade_home/AGENTS.md" "Keep this before the managed block."
assert_contains "$upgrade_home/AGENTS.md" "Keep this after the managed block."
[ "$(grep -Fc '# BEGIN PRODKIT GITHUB PUBLISHING POLICY' "$upgrade_home/AGENTS.md")" -eq 1 ] || fail "managed policy was duplicated"
cp "$upgrade_home/AGENTS.md" "$tmp_root/agents.once"
run_setup "$upgrade_home" >/dev/null 2>&1
cmp -s "$tmp_root/agents.once" "$upgrade_home/AGENTS.md" || fail "repeated setup changed AGENTS.md"

# A non-empty override file remains the authoritative Codex global instruction target.
override_home="$tmp_root/override"
mkdir -p "$override_home"
printf '%s\n' '# base instructions' > "$override_home/AGENTS.md"
printf '%s\n' '# override instructions' > "$override_home/AGENTS.override.md"
run_setup "$override_home" >/dev/null 2>&1
assert_not_contains "$override_home/AGENTS.md" "BEGIN PRODKIT GITHUB PUBLISHING POLICY"
assert_contains "$override_home/AGENTS.override.md" "BEGIN PRODKIT GITHUB PUBLISHING POLICY"

# An installed but unauthenticated gh is detected without failing setup.
fakebin="$tmp_root/bin"
mkdir -p "$fakebin"
cat > "$fakebin/prodkit-gh" <<'EOF_GH'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then
  echo "gh version test"
  exit 0
fi
if [ "${1:-}" = "auth" ] && [ "${2:-}" = "status" ]; then
  exit 1
fi
exit 2
EOF_GH
chmod +x "$fakebin/prodkit-gh"
unauth_home="$tmp_root/unauth"
PATH="$fakebin:$PATH" \
CODEX_HOME="$unauth_home" \
PRODKIT_CODEX_GH_COMMAND="prodkit-gh" \
PRODKIT_CODEX_APT_GET_COMMAND="prodkit-missing-apt-get" \
bash "$setup_script" > "$tmp_root/unauth.log" 2>&1
assert_contains "$tmp_root/unauth.log" "GitHub CLI is not authenticated"

# Failed installation remains non-fatal and sudo is always invoked non-interactively.
cat > "$fakebin/prodkit-apt" <<'EOF_APT'
#!/usr/bin/env bash
exit 42
EOF_APT
cat > "$fakebin/prodkit-sudo" <<'EOF_SUDO'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${PRODKIT_TEST_SUDO_LOG:?}"
[ "${1:-}" = "-n" ] || exit 97
shift
exec "$@"
EOF_SUDO
chmod +x "$fakebin/prodkit-apt" "$fakebin/prodkit-sudo"
install_home="$tmp_root/install-failure"
sudo_log="$tmp_root/sudo.log"
PATH="$fakebin:$PATH" \
CODEX_HOME="$install_home" \
PRODKIT_CODEX_GH_COMMAND="prodkit-missing-gh" \
PRODKIT_CODEX_APT_GET_COMMAND="prodkit-apt" \
PRODKIT_CODEX_SUDO_COMMAND="prodkit-sudo" \
PRODKIT_CODEX_EFFECTIVE_UID=1000 \
PRODKIT_TEST_SUDO_LOG="$sudo_log" \
bash "$setup_script" > "$tmp_root/install.log" 2>&1
assert_contains "$tmp_root/install.log" "GitHub CLI installation failed"
assert_contains "$sudo_log" "-n prodkit-apt update"

echo "Codex setup tests passed."
