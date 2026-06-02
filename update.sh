#!/bin/bash
set -euo pipefail

# Update the Bonzai Hermes plugin to the latest version.
#
# Two scenarios:
#   1. You are inside a git clone of this repo -> pulls latest, then installs.
#   2. You ran the one-liner before (no local clone) -> use the one-liner again
#      (see README "Updating"); this script will still re-install whatever
#      files sit next to it.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Updating Bonzai Hermes plugin..."

# --- 1. Pull latest if this is a git checkout ---
if [ -d "$SCRIPT_DIR/.git" ]; then
    echo "Git checkout detected — pulling latest..."
    git -C "$SCRIPT_DIR" pull --ff-only
else
    echo "ℹ️  Not a git checkout — installing the files in $SCRIPT_DIR as-is."
    echo "   For a true update, re-run the one-liner from the README."
fi

# --- 2. Re-run the installer (idempotent: refreshes files, overlay, cache) ---
echo ""
"$SCRIPT_DIR/install.sh"

echo ""
echo "Update complete. Restart Hermes for the new version to take effect."
