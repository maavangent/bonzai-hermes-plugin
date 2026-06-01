#!/bin/bash
set -e

PLUGIN_DIR="$HOME/.hermes/plugins/model-providers/bonzai"

echo "Installing Bonzai Hermes plugin..."

# Remove old installation if it exists
if [ -d "$PLUGIN_DIR" ]; then
    echo "Removing existing installation..."
    rm -rf "$PLUGIN_DIR"
fi

# Create parent directory if needed
mkdir -p "$(dirname "$PLUGIN_DIR")"

# Copy plugin
cp -r "$(dirname "$0")/bonzai" "$PLUGIN_DIR"

echo "✅ Bonzai plugin installed successfully."
echo "Please restart Hermes for the changes to take effect."