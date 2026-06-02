#!/bin/bash
set -euo pipefail

# Resolve paths
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DIR="$HERMES_HOME/plugins/model-providers/bonzai"
PROVIDERS_FILE="$HERMES_HOME/hermes-agent/hermes_cli/providers.py"
CACHE_FILE="$HERMES_HOME/provider_models_cache.json"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing Bonzai Hermes plugin..."

# --- 1. Copy plugin files ---
if [ -d "$PLUGIN_DIR" ]; then
    echo "Removing existing installation..."
    rm -rf "$PLUGIN_DIR"
fi
mkdir -p "$(dirname "$PLUGIN_DIR")"
cp -r "$SCRIPT_DIR/bonzai" "$PLUGIN_DIR"
echo "✅ Plugin files installed to $PLUGIN_DIR"

# --- 2. Register HermesOverlay (best effort) ---
# Model-provider plugins are auto-discovered from this directory, but the
# CLI/switching layer also needs a matching HermesOverlay entry, otherwise
# `hermes model` reports "Unknown provider 'bonzai'".
if [ -f "$PROVIDERS_FILE" ]; then
    # Pass the path as argv[1] so $HOME expansion happens in the SHELL, not
    # inside the (single-quoted, non-expanding) heredoc.
    python3 - "$PROVIDERS_FILE" <<'PYEOF'
import re
import sys

path = sys.argv[1]

with open(path, "r") as f:
    content = f.read()

if '"bonzai"' in content:
    print("ℹ️  Overlay for 'bonzai' already present.")
    sys.exit(0)

overlay = (
    '    "bonzai": HermesOverlay(\n'
    '        transport="openai_chat",\n'
    '        auth_type="api_key",\n'
    '        base_url_override="https://api-v2.bonzai.iodigital.com/",\n'
    '        extra_env_vars=("BONZAI_API_KEY",),\n'
    '    ),\n'
)

# Insert just before the closing brace of the HERMES_OVERLAYS dict.
# The dict literal ends with a line containing only "}" right after the
# last "    )," entry. We anchor on that closing brace.
m = re.search(r'(HERMES_OVERLAYS\s*:\s*Dict\[str,\s*HermesOverlay\]\s*=\s*\{)(.*?)(\n\})',
              content, re.DOTALL)
if not m:
    print("⚠️  Could not locate HERMES_OVERLAYS dict — add overlay manually (see README).")
    sys.exit(1)

new_block = m.group(1) + m.group(2) + "\n" + overlay + m.group(3)
new_content = content[:m.start()] + new_block + content[m.end():]

if new_content == content:
    print("⚠️  Overlay insertion produced no change — add manually (see README).")
    sys.exit(1)

with open(path, "w") as f:
    f.write(new_content)
print("✅ HermesOverlay entry added to providers.py")
PYEOF
else
    echo "⚠️  providers.py not found at $PROVIDERS_FILE"
    echo "   Add the HermesOverlay entry manually (see README)."
fi

# --- 3. Clear model cache so the new provider shows up ---
if [ -f "$CACHE_FILE" ]; then
    rm -f "$CACHE_FILE"
    echo "✅ Cleared model cache."
fi

echo ""
echo "Installation complete. Restart Hermes (or 'hermes gateway restart')."
echo "Then run 'hermes model' and select the 'bonzai' provider."
