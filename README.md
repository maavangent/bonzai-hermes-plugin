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

## Updating

To pull the latest version and re-install in one go:

```bash
git clone https://github.com/maavangent/bonzai-hermes-plugin /tmp/bonzai-plugin && \
cd /tmp/bonzai-plugin && \
./update.sh && \
rm -rf /tmp/bonzai-plugin
```

If you keep a local clone of this repo, just run:

```bash
./update.sh
```

`update.sh` pulls the latest code (when run from a git checkout) and then re-runs `install.sh`, which is fully idempotent — it refreshes the plugin files, leaves the existing overlay untouched, and clears the model cache. Restart Hermes afterwards.

## Configuration

Add your API key to `~/.hermes/.env`:

```env
BONZAI_API_KEY=your-key-here
```

## Usage

`install.sh` does everything automatically:

1. Copies the plugin into `~/.hermes/plugins/model-providers/bonzai/` (auto-discovered by Hermes — no `plugins enable` needed)
2. Adds the required `HermesOverlay` entry to `providers.py`
3. Clears the model cache

After installing, just restart Hermes (or `hermes gateway restart`), then:

```bash
hermes model
```

Select the `bonzai` provider (or use `/model` inside the TUI).

## Uninstall

```bash
./uninstall.sh
```

This removes the plugin files, the `HermesOverlay` entry, and the model cache. Restart Hermes afterwards. If `bonzai` was your active model, switch to another with `hermes model` first.

## Troubleshooting

If you still get **"Unknown provider 'bonzai'"**:

1. Verify the overlay was added:
   ```bash
   grep -A 6 '"bonzai"' ~/.hermes/hermes-agent/hermes_cli/providers.py
   ```

2. If missing, add it manually — edit `~/.hermes/hermes-agent/hermes_cli/providers.py` and insert inside `HERMES_OVERLAYS`:

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

Note: the overlay lives in the Hermes source tree, so it may need to be re-added after a major `hermes update`. Just re-run `./install.sh`.