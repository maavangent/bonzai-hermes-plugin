# Bonzai Hermes Plugin

Hermes model provider plugin for the internal Bonzai API at iO.

## Installation

### One-command install via Git (recommended)

```bash
git clone https://github.com/maavangent/bonzai-hermes-plugin /tmp/bonzai-plugin && \
cd /tmp/bonzai-plugin && \
./install.sh && \
rm -rf /tmp/bonzai-plugin
```

### Install from ZIP file

If you received the plugin as a `.zip` file:

1. Unzip the file
2. Open a terminal and navigate into the unzipped folder
3. Run the installer:

```bash
./install.sh
```

### Manual Git install

```bash
git clone https://github.com/maavangent/bonzai-hermes-plugin ~/.hermes/plugins/model-providers/bonzai-temp
mv ~/.hermes/plugins/model-providers/bonzai-temp/bonzai ~/.hermes/plugins/model-providers/bonzai
rm -rf ~/.hermes/plugins/model-providers/bonzai-temp
```

After installation, the `install.sh` script will automatically try to register the required HermesOverlay.

## Configuration

Add your API key to `~/.hermes/.env`:

```env
BONZAI_API_KEY=your-key-here
```

## Usage

The `install.sh` now automatically adds the HermesOverlay entry.

After installation:

```bash
rm ~/.hermes/provider_models_cache.json
```

Then restart Hermes completely.

You can now use the provider with:

```bash
hermes model
```

Or `/model` inside the TUI.

## Troubleshooting

If you still get **"Unknown provider 'bonzai'"**:

1. Verify the overlay was added:
   ```bash
   grep -A 6 '"bonzai"' ~/.hermes/hermes-agent/hermes_cli/providers.py
   ```

2. If missing, add it manually:

   Edit `~/.hermes/hermes-agent/hermes_cli/providers.py` and insert inside `HERMES_OVERLAYS`:

   ```python
   "bonzai": HermesOverlay(
       transport="openai_chat",
       auth_type="api_key",
       base_url_override="https://api-v2.bonzai.iodigital.com/",
       extra_env_vars=("BONZAI_API_KEY",),
   ),
   ```

3. Clear cache and restart:
   ```bash
   rm ~/.hermes/provider_models_cache.json
   ```

## Advanced

If the automatic overlay insertion fails (rare), you can also run the installer again or manually apply the change shown above.