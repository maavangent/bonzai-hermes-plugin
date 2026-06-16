# Bonzai Hermes Plugin

Hermes model provider plugin for the internal Bonzai API at iO.

Works on **macOS, Linux and Windows**. The installer is a single cross-platform
Python script (`install.py`) — no bash required, so it runs in PowerShell,
Windows Terminal, Terminal.app, or any shell with Python 3.

## Requirements

- [Hermes Agent](https://hermes-agent.nousresearch.com/) installed (desktop app or CLI)
- Python 3 (ships with Hermes; on Windows it's available as `python`)
- `git` (for the one-command install)

## Installation

### One-command install (recommended)

**macOS / Linux:**

```bash
git clone https://github.com/maavangent/bonzai-hermes-plugin /tmp/bonzai-plugin && \
cd /tmp/bonzai-plugin && \
python3 install.py && \
rm -rf /tmp/bonzai-plugin
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/maavangent/bonzai-hermes-plugin $env:TEMP\bonzai-plugin; `
cd $env:TEMP\bonzai-plugin; `
python install.py; `
cd ~; Remove-Item -Recurse -Force $env:TEMP\bonzai-plugin
```

### Install from a local clone or ZIP

If you already cloned the repo (or unzipped a download), just run from inside it:

```bash
python install.py          # macOS / Linux
python install.py          # Windows (use `python`, not `python3`)
```

## Configuration

Add your API key to `~/.hermes/.env` (on Windows: `%USERPROFILE%\.hermes\.env`):

```env
BONZAI_API_KEY=your-key-here
```

## What the installer does

`install.py` is fully idempotent and does everything automatically:

1. Copies the plugin into `~/.hermes/plugins/model-providers/bonzai/`
   (auto-discovered by Hermes — no `plugins enable` needed)
2. Injects the required `HermesOverlay` entry into `hermes_cli/providers.py`
   so `hermes model` / `/model` recognise the provider (without it you get
   *"Unknown provider 'bonzai'"*)
3. Clears the model cache so the new provider shows up

It honors the `HERMES_HOME` environment variable and falls back to `~/.hermes`.

After installing, restart Hermes (or `hermes gateway restart`), then run:

```bash
hermes model
```

Select the `bonzai` provider (or use `/model` inside the TUI / desktop app).

## Updating

```bash
git clone https://github.com/maavangent/bonzai-hermes-plugin /tmp/bonzai-plugin && \
cd /tmp/bonzai-plugin && \
python3 install.py --update && \
rm -rf /tmp/bonzai-plugin
```

Or, from a local checkout:

```bash
python install.py --update
```

`--update` pulls the latest code (when run from a git checkout) and then
re-runs the install, which refreshes the plugin files, leaves the existing
overlay untouched, and clears the model cache. Restart Hermes afterwards.

## Uninstall

```bash
python install.py --uninstall
```

This removes the plugin files, the `HermesOverlay` entry, and the model cache.
Restart Hermes afterwards. If `bonzai` was your active model, switch to another
with `hermes model` first.

## Troubleshooting

**"Unknown provider 'bonzai'"** after install:

1. Verify the overlay was added:

   ```bash
   # macOS / Linux
   grep -A6 '"bonzai"' ~/.hermes/hermes-agent/hermes_cli/providers.py
   ```
   ```powershell
   # Windows
   Select-String -Path "$env:USERPROFILE\.hermes\hermes-agent\hermes_cli\providers.py" -Pattern bonzai
   ```

2. If missing, re-run `python install.py`, or add it manually inside
   `HERMES_OVERLAYS`:

   ```python
   "bonzai": HermesOverlay(
       transport="openai_chat",
       auth_type="api_key",
       base_url_override="https://api-v2.bonzai.iodigital.com/",
       extra_env_vars=("BONZAI_API_KEY",),
   ),
   ```

3. Clear the cache and restart Hermes:

   ```bash
   rm ~/.hermes/provider_models_cache.json
   ```

**Provider not visible after install** — restart Hermes *completely* (the
overlay in `providers.py` is read once at startup), not just a new session.

**Switch from another provider fails on cold start** — use `hermes model` to
explicitly pick a Bonzai model. That forces a clean provider + credential
resolution. To avoid it, set Bonzai as your default:

```bash
hermes config set model.default claude-sonnet-4-6
hermes config set model.provider bonzai
```

> Note: the overlay lives in the Hermes source tree, so it may need to be
> re-added after a major `hermes update`. Just re-run `python install.py`.

## Legacy bash scripts

The original `install.sh` / `update.sh` / `uninstall.sh` are kept for
backwards compatibility on macOS/Linux but are no longer the recommended path.
`install.py` supersedes all three and is the only one that works on Windows.
