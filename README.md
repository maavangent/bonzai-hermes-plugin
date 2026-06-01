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

The plugin will automatically appear as the `bonzai` provider. You can switch to it using:

```bash
hermes model switch --provider bonzai
```

Or use `/model` in the TUI.

## Troubleshooting

If you don't see the latest models after installing/updating the plugin, clear Hermes' model cache:

```bash
rm ~/.hermes/provider_models_cache.json
```

Then restart Hermes.