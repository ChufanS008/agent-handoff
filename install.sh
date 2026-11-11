#!/bin/sh
# Copy agent-handoff to ~/.local/share/agent-handoff, write a starter config, create the shared layout.
# Hooks are printed, not merged, so your existing settings stay untouched.
set -e
DEST="${AGENT_HANDOFF_HOME:-$HOME/.local/share/agent-handoff}"
CFG="${AGENT_HANDOFF_CONFIG:-$HOME/.config/agent-handoff/config.json}"
SRC="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$DEST" "$(dirname "$CFG")"
cp -R "$SRC/handoff" "$SRC/templates" "$SRC/hooks" "$DEST/"
if [ ! -f "$CFG" ]; then
  printf '{\n  "root": "~/agent-kb",\n  "projects": []\n}\n' > "$CFG"
  echo "wrote $CFG (edit root and projects)"
fi
python3 "$DEST/handoff/agent_handoff.py" init

cat <<MSG

Next steps
1. Claude Code: merge $DEST/hooks/claude-settings.json into ~/.claude/settings.json
2. Codex: merge $DEST/hooks/codex-hooks.json into ~/.codex/hooks.json
3. Paste templates/agent/CLAUDE.md.snippet into ~/.claude/CLAUDE.md
   and templates/agent/AGENTS.md.snippet into ~/.codex/AGENTS.md
4. Try it: python3 $DEST/handoff/agent_handoff.py recent
MSG
