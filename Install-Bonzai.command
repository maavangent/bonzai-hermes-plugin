#!/usr/bin/env bash
cd "$(dirname "$0")"

# Search for Hermes Python runtime first, then system python3/python
HERMES_PY="$HOME/.hermes/hermes-agent/venv/bin/python3"
if [ ! -f "$HERMES_PY" ]; then
    HERMES_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
fi
if [ ! -f "$HERMES_PY" ]; then
    HERMES_PY="$HOME/venv/bin/python3"
fi
if [ ! -f "$HERMES_PY" ]; then
    HERMES_PY="$(which python3 2>/dev/null || which python 2>/dev/null)"
fi

if [ -z "$HERMES_PY" ]; then
    echo "❌ No Python runtime found. Please ensure Hermes Agent is installed."
    read -n 1 -s -r -p "Press any key to exit..."
    exit 1
fi

"$HERMES_PY" install.py --interactive
echo ""
read -n 1 -s -r -p "Press any key to close this window..."
echo ""
