# Bonzai Hermes Plugin

Hermes model provider plugin for the internal Bonzai API at iO.

Works on **macOS, Linux and Windows**. The installer is a single cross-platform
Python script (`install.py`) — no bash required, so it runs in PowerShell,
Windows Terminal, Terminal.app, or any shell with Python 3.

## Requirements

- [Hermes Agent](https://hermes-agent.nousresearch.com/) installed (desktop app or CLI)
- Python 3 (ships with Hermes)
- `git` (for the one-command install)
- A Bonzai API key — get one at [bonzai.iodigital.com](https://bonzai.iodigital.com/)

You do **not** need to manually add an API key — `hermes model` asks for your
`BONZAI_API_KEY` during setup and stores it for you (see step 2 below).

## Installation

The install is two steps: install the plugin, then configure it with `hermes model`.

### Step 1 — Install the plugin

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

> Already have a local clone or unzipped download? Just run `python install.py`
> (use `python3` on macOS/Linux, `python` on Windows) from inside the folder.

Then **restart Hermes** (or `hermes gateway restart`) so the new provider loads.

### Step 2 — Configure with `hermes model`

```bash
hermes model
```

This launches Hermes' built-in setup wizard:

1. Select the **Bonzai** provider from the list
2. Paste your `BONZAI_API_KEY` when prompted — Hermes stores it in `.env` for you
3. Confirm the base URL (already filled in: `https://api-v2.bonzai.iodigital.com/`)
4. Pick a model (e.g. `claude-sonnet-4-6`)

That's it — Bonzai is now your active provider.

## What the installer does

`install.py` is fully idempotent and handles the plumbing automatically:

1. Copies the plugin into `~/.hermes/plugins/model-providers/bonzai/`
   (auto-discovered by Hermes — no `plugins enable` needed)
2. Injects the required `HermesOverlay` entry into `hermes_cli/providers.py`
   so `hermes model` / `/model` recognise the provider (without it you get
   *"Unknown provider 'bonzai'"*)
3. Clears the model cache so the new provider shows up

It honors the `HERMES_HOME` environment variable and falls back to `~/.hermes`.
The API key itself is handled by `hermes model` in step 2 above, not by the
installer.

## Health check

```bash
python install.py --check
```

Reports whether the plugin directory and the `HermesOverlay` entry are both
in place, and exits non-zero when something is wrong. Worth running after every
`hermes update`: a major update replaces the Hermes source tree and silently
drops the overlay, after which `/model` reports *"Unknown provider 'bonzai'"*
even though the plugin itself loaded fine. `python install.py` repairs it.

## Which models you see

`fetch_models` builds a two-tier picker list from the live Bonzai catalog:

- **Tier 1** — the **two newest versions of every family** (Opus 5 + 4.8,
  Sonnet 5 + 4.6, GPT-5.6 + 5.5, …). When one version ships as several named
  variants (`gpt-5.6-luna` / `-sol` / `-terra`) all of them come along, since
  they are one release you need to choose between.
- **Separator line**
- **Tier 2** — everything else that is still callable: older versions and the
  lightweight tiers (`-mini`, `-nano`, `-flash`, `-lite`).

Hidden entirely: pure duplicates (`-bedrock` / `-vertex` routes, `eu.anthropic.*`
prefixes, date-stamped snapshots), compliance-bypassing `uncompliant-global-*`
models, and non-chat models (image / TTS / whisper / embeddings / rerank).

Also hidden: **version-first Claude ids** (`claude-3-haiku`, `claude-4-sonnet`).
The desktop picker builds its label straight from the model id, so these render
as *"3 Haiku"* / *"4 Sonnet"* right next to *"Haiku 4 5"* — the same family in two
word orders. The id cannot be rewritten to fix the label, because the string
returned by `fetch_models` is also the id sent to the API (`claude-haiku-3` is not
a model Bonzai serves). When the API exposes both spellings the clean
family-first one wins the dedupe; when version-first is the *only* spelling the
model is dropped rather than shown inconsistently. Everything visible therefore
reads `[name] [version]`.

New families are never dropped — anything the regexes don't recognise falls
through to tier 2 instead of disappearing.

Every successful fetch is also written to `$HERMES_HOME/bonzai_models_cache.json`.
An offline start reuses that last-known-good list, so the plugin deliberately
ships **no** `fallback_models`: Hermes merges that tuple *ahead* of the live list,
which would pin a stale hand-written order to the top of the picker and bury
newly released flagships.

### Desktop app: new models start hidden

This is Hermes core behaviour, not something the plugin controls. The desktop
model dropdown persists an explicit visible-model set the first time you toggle
anything (`hermes.desktop.visible-models` in localStorage). From then on a model
the provider adds *later* is **not** auto-enabled — Hermes only expands its
curated defaults for providers you have never customised.

So after a new Bonzai model appears, open the model dropdown → **Edit models**
and switch it on once. The plugin's job is to put it at the top of the list,
which it now does.

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
