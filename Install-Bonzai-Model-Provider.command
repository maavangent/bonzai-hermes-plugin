#!/usr/bin/env bash
cd "$(dirname "$0")"

# Prefer Hermes' own Python: it has PyYAML and preserves config.yaml comments.
HERMES_PY=""
for candidate in \
    "$HOME/.hermes/hermes-agent/venv/bin/python3" \
    "$HOME/.hermes/hermes-agent/venv/bin/python" \
    "$HOME/.local/share/hermes-agent/venv/bin/python3"; do
    if [ -x "$candidate" ]; then
        HERMES_PY="$candidate"
        break
    fi
done
if [ -z "$HERMES_PY" ]; then
    HERMES_PY="$(command -v python3 || command -v python || true)"
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
