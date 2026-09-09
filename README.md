# Bonzai Hermes Plugin

Hermes model provider plugin for the internal Bonzai API at iO, with built-in multi-key alias support and a native Desktop companion for Hermes Desktop.

Works on **macOS, Linux and Windows**.

---

## Quick Start (For All Colleagues)

### Option A: One-Click Launcher (Easiest — No Terminal Needed)

1. Download or clone this repository to your computer.
2. Run the launcher for your operating system:
   - **macOS:** Double-click `Install-Bonzai.command`
   - **Windows:** Double-click `Install-Bonzai.cmd`
3. Paste your Bonzai API key when prompted (grab one at [bonzai.iodigital.com](https://bonzai.iodigital.com/)).
4. Open or restart **Hermes Desktop** — Bonzai is immediately ready with `gemini-3.7-flash` as your active default model!

---

### Option B: One-Command Terminal Install

**macOS / Linux:**

```bash
git clone https://github.com/maavangent/bonzai-hermes-plugin /tmp/bonzai-plugin && \
cd /tmp/bonzai-plugin && \
python3 install.py --interactive && \
rm -rf /tmp/bonzai-plugin
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/maavangent/bonzai-hermes-plugin $env:TEMP\bonzai-plugin; `
cd $env:TEMP\bonzai-plugin; `
python install.py --interactive; `
cd ~; Remove-Item -Recurse -Force $env:TEMP\bonzai-plugin
```

---

## Managing Keys in Hermes Desktop UI (Bonzai Key Manager)

The plugin automatically installs the **Bonzai Key Manager** desktop extension. Once installed, you can manage your keys and client credentials directly inside the Hermes Desktop app:

1. **Status Bar Chip (Bottom-Right):**  
   Click the **🌿 Bonzai** chip in the bottom-right corner of Hermes Desktop to open a quick popover with your active credentials and rotation settings.
2. **Dedicated Sidebar Pane:**  
   Open the **Bonzai Keys** panel on the right sidebar to add, test, rename, or remove API keys with a visual form.
3. **Command Palette (`⌘K` / `Ctrl+K`):**  
   Type `Bonzai: Locate key manager` to instantly focus the key manager pane.

---

## Multiple API Keys & Client Billing (Model Aliases)

Need to route Bonzai API costs to specific client accounts (e.g. Landal, Heineken)? You can set up named **client aliases** to switch seamlessly inside any chat session.

### Method 1: Via the Setup Wizard (Recommended)

Run `python install.py --add-alias` (or select Option 2 in `Install-Bonzai.command` / `Install-Bonzai.cmd`):

```text
====================================================
  🌿 Add a Client-Specific Bonzai Alias
====================================================
Client name (e.g. landal, heineken): landal
Paste the Bonzai API Key for 'landal': sk-bonzai-landal-...
Preferred model [gemini-3.7-flash]: gemini-3.7-flash

✅ Client alias 'landal' added!
```

### Method 2: Directly in Hermes Chat

You can configure client keys directly in your chat:

1. Store the client's API key:
   ```text
   /env set BONZAI_LANDAL_API_KEY=sk-bonzai-landal-...
   ```
2. Configure the alias in `~/.hermes/config.yaml`:
   ```yaml
   model_aliases:
     landal:
       model: gemini-3.7-flash
       provider: custom
       base_url: "https://api-v2.bonzai.iodigital.com"
       key_env: BONZAI_LANDAL_API_KEY
   ```
3. Switch anytime in chat:
   ```text
   /model landal
   /model io
   ```

---

## Upgrading from a Previous Version

If you or your colleagues already have an older version of the Bonzai plugin installed:

- **Simply run `Install-Bonzai.command` (or `python install.py`) again.**
- The installer is fully idempotent: it detects previous installations, replaces the plugin files with the latest version, refreshes the provider overlay, and **preserves your existing API keys and configurations**.
- If an existing key is detected, the installer gives you the option to keep it, assign it to a client alias, or replace it.
- Restart Hermes Desktop after updating.

---

## What the Installer Does

`install.py` handles the plumbing automatically:

1. Copies the provider into `~/.hermes/plugins/model-providers/bonzai/` (auto-discovered by Hermes).
2. Copies and enables the backend at `~/.hermes/plugins/bonzai-key-manager/`.
3. Copies the Desktop companion to `~/.hermes/desktop-plugins/bonzai-key-manager/plugin.js`.
4. Injects the `HermesOverlay` entry into `hermes_cli/providers.py` so `/model` and the model picker recognise Bonzai.
5. Sets `model.provider: bonzai` and `model.default: gemini-3.7-flash` in `config.yaml`.
6. Sets up the default `io` model alias in `config.yaml`.
7. Clears the model cache so newly added models appear immediately.

It honors the `HERMES_HOME` environment variable and falls back to `~/.hermes`.

---

## Health Check

Run a diagnostic check at any time:

```bash
python install.py --check
```

Reports whether the provider directory, overlay, Key Manager backend, Desktop companion, and API key are properly configured.

---

## Uninstall

To completely remove the Bonzai plugin, overlay, Desktop companion, and model cache:

```bash
python install.py --uninstall
```

Restart Hermes afterwards.

---

## Which Models You See

`fetch_models` builds a clean two-tier picker list from the live Bonzai catalog:

- **Tier 1 (Top of list)** — The **two newest versions of every flagship family** (Gemini Flash/Pro, Claude Sonnet/Opus, GPT-5, GLM, Codestral).
- **Tier 2** — All other callable models, older versions, and lightweight tiers (`-mini`, `-nano`, `-flash`, `-lite`).

**Filtered out automatically:**
- Non-chat endpoints (image generation, TTS, speech-to-text, embeddings, rerankers).
- Compliance-bypassing `uncompliant-global-*` models.
- Backend routing duplicates (`-bedrock`, `-vertex`, `eu.anthropic.*`, date-stamped snapshots).
- Claude duplicate naming schemes (`claude-4-5-sonnet` vs `claude-sonnet-4-5`).

Every successful fetch is cached in `$HERMES_HOME/bonzai_models_cache.json` for offline resilience.

---

## License

MIT © iO Digital / Maarten van Gent
