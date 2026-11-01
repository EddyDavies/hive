#!/usr/bin/env bash
# Install the hive CLI (editable, via uv) and link its two skills (hive-queen, hive-bee) into ~/.claude/skills.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
uv tool uninstall herd >/dev/null 2>&1 || true  # the tool's old name
rm -f "$HOME/.claude/skills/herd-shepherd" "$HOME/.claude/skills/herd-sheepdog"
uv tool install --editable "$here" --force
for s in hive-queen hive-bee; do
  ln -sfn "$here/skills/$s" "$HOME/.claude/skills/$s"
done
echo "hive installed: $(command -v hive)"
