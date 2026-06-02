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

After installation, restart Hermes.

### Manual Git install

```bash
git clone https://github.com/maavangent/bonzai-hermes-plugin ~/.hermes/plugins/model-providers/bonzai-temp
mv ~/.hermes/plugins/model-providers/bonzai-temp/bonzai ~/.hermes/plugins/model-providers/bonzai
rm -rf ~/.hermes/plugins/model-providers/bonzai-temp
```

After installation, restart Hermes.

## Configuration

Add your API key to `~/.hermes/.env`:

```env
BONZAI_API_KEY=your-key-here
```

## Usage

After installing the plugin you **must** add a Hermes overlay entry so the CLI recognizes the provider.

### 1. Add overlay (required one-time step)

Edit `~/.hermes/hermes-agent/hermes_cli/providers.py` and add this entry inside the `HERMES_OVERLAYS` dictionary:

```python
"bonzai": HermesOverlay(
    transport="openai_chat",
    auth_type="api_key",
    base_url_override="https://api-v2.bonzai.iodigital.com/",
    extra_env_vars=("BONZAI_API_KEY",),
),
```

### 2. Clear cache & restart

```bash
rm ~/.hermes/provider_models_cache.json
```

Then restart Hermes (or the gateway).

You can now switch to the provider using:

```bash
hermes model
```

Or use `/model` in the TUI.

## Troubleshooting

If you see **"Unknown provider 'bonzai'"**:

- Make sure you added the `HermesOverlay` entry above
- Clear the cache: `rm ~/.hermes/provider_models_cache.json`
- Restart Hermes completely

If you don't see the latest models after installing/updating the plugin, clear Hermes' model cache:

```bash
rm ~/.hermes/provider_models_cache.json
```

Then restart Hermes.