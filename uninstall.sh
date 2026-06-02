#!/bin/bash
set -euo pipefail

# Mirror of install.sh — removes plugin files, the HermesOverlay entry, and the cache.

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DIR="$HERMES_HOME/plugins/model-providers/bonzai"
PROVIDERS_FILE="$HERMES_HOME/hermes-agent/hermes_cli/providers.py"
CACHE_FILE="$HERMES_HOME/provider_models_cache.json"

echo "Uninstalling Bonzai Hermes plugin..."

# --- 1. Remove plugin files ---
if [ -d "$PLUGIN_DIR" ]; then
    rm -rf "$PLUGIN_DIR"
    echo "✅ Removed $PLUGIN_DIR"
else
    echo "ℹ️  Plugin dir not found (already removed)."
fi

# --- 2. Remove the HermesOverlay entry ---
if [ -f "$PROVIDERS_FILE" ]; then
    python3 - "$PROVIDERS_FILE" <<'PYEOF'
import re
import sys

path = sys.argv[1]
with open(path, "r") as f:
    content = f.read()

# Remove the whole "bonzai": HermesOverlay(...), block, including a leading
# newline, regardless of internal formatting.
pattern = r'\n[ \t]*"bonzai":\s*HermesOverlay\((?:[^()]*|\([^()]*\))*\),'
new_content, n = re.subn(pattern, "", content, count=1)

if n == 0:
    print("ℹ️  No 'bonzai' overlay entry found.")
    sys.exit(0)

with open(path, "w") as f:
    f.write(new_content)
print("✅ Removed HermesOverlay entry from providers.py")
PYEOF
else
    echo "ℹ️  providers.py not found; nothing to clean there."
fi

# --- 3. Clear model cache ---
if [ -f "$CACHE_FILE" ]; then
    rm -f "$CACHE_FILE"
    echo "✅ Cleared model cache."
fi

echo ""
echo "Uninstall complete. Restart Hermes (or 'hermes gateway restart')."
echo "If 'bonzai' was your active model, switch with 'hermes model' first."
