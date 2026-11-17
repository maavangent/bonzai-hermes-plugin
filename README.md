# Bonzai Hermes Plugin

This repository includes the Bonzai provider, installer, Key Manager backend and Hermes Desktop companion extension. Hermes Desktop core model-picker changes are maintained separately in the Hermes repository.

Current versions: **provider 2.11.0**, **Key Manager 2.1.0**.

Works on **macOS, Linux and Windows**.

---

## Prerequisites

Before installing the Bonzai plugin, make sure you have:
1. **[Hermes Desktop App](https://hermes-agent.nousresearch.com/)** installed on your computer.
2. A **Bonzai API Key** from [bonzai.iodigital.com](https://bonzai.iodigital.com/).

**Hermes update compatibility**

Hermes 0.22.0 and newer uses native registered-provider resolution. Older versions use the compatibility overlay.

---

## Installation

Choose the method that works best for you:

### Method 1: One-Line Terminal Command (Recommended)

Copy and paste this single command into your terminal:

**macOS / Linux (Terminal):**
```bash
git clone https://github.com/maavangent/bonzai-hermes-plugin /tmp/bonzai-plugin && cd /tmp/bonzai-plugin && python3 install.py --interactive && rm -rf /tmp/bonzai-plugin
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/maavangent/bonzai-hermes-plugin $env:TEMP\bonzai-plugin; cd $env:TEMP\bonzai-plugin; python install.py --interactive; cd ~; Remove-Item -Recurse -Force $env:TEMP\bonzai-plugin
```

---

### Method 2: Direct Download / One-Click Launcher (No Git Required)

1. **[Download the ZIP file](https://github.com/maavangent/bonzai-hermes-plugin/archive/refs/heads/main.zip)** and extract it to your Downloads folder.
2. Open the extracted `bonzai-hermes-plugin-main` folder and run the launcher for your operating system:
   - **macOS:** Double-click **`Install-Bonzai-Model-Provider.command`**
   - **Windows:** Double-click **`Install-Bonzai-Model-Provider.cmd`**
3. When prompted, paste your Bonzai API key (grab one at [bonzai.iodigital.com](https://bonzai.iodigital.com/)).
4. Open **Hermes Desktop**. A fresh setup uses **Luna 6.0 (`gpt-6-luna`)**; an existing model selection is preserved. Use `/model io` to select Bonzai.

---

## Managing Keys in Hermes Desktop UI (Bonzai Key Manager)

The plugin automatically installs the **Bonzai Key Manager** desktop extension:

1. **Status Bar (Bottom-Right):**  
   Click the **Bonzai · …** chip in the bottom-right corner to see which key the focused chat uses, switch keys, or add a client key.
2. **Right Sidebar Pane:**  
   Open the **Bonzai Keys** panel on the right sidebar for the same controls in a pane.
3. **Command Palette (`⌘K` / `Ctrl+K`):**  
   `Bonzai: Select client key` opens the registered Bonzai settings page, with a dedicated-page fallback on older SDKs.

The panel offers **Rename** and **Test** for existing client keys. Testing happens on the backend; the stored key is never sent back to the renderer. The panel uses owner-routed session information to detect inactive providers, but the current Hermes session API does not expose an authoritative credential ID. **Selected** is advisory, **Pending** is not confirmed active, and **Key unverified** is deliberate rather than a guessed billing identity.

Picking a key switches **only the focused chat**, and key switching waits until the chat is idle. If Hermes unexpectedly defers a switch because a turn starts during the request, the panel retains an unverified Pending selection across plugin reload; select a key again once idle to resolve it. If Hermes rejects the switch, the chat keeps its current key and the menu shows the error. A client key selected in a chat cannot be removed until you select another key there.

Client aliases are not a strict credential pin. A configured Hermes fallback chain can switch to another provider after an error; the plugin does not disable that core behavior. Keep fallback disabled for work that requires strict account separation, or use a separately configured client profile. A displayed alias/model selection is not an invoice-level proof of which account the provider billed.

### How client keys are kept separate

A client key is stored as its own `.env` secret plus a `model_aliases` entry, never in the Bonzai credential pool. Hermes rotates pool keys automatically after a rate limit or a rejected key, so a pooled client key could silently bill iO work to that client, or the reverse. Key Manager 2.0 moves client keys that older versions put in the pool into aliases the first time Hermes Desktop loads it; `python install.py --check` reports any that remain.

The Key Manager resolves the focused chat's owning Desktop connection and Hermes profile before switching a key. It preserves the chat's current model, or uses the configured Hermes default when no current model is available. Client keys use a stable named `providers:` endpoint with a server-side `key_env`; legacy `model_aliases` stay unchanged for typed `/model` commands. The default key uses the Bonzai provider. The routed `session.model` adapter carries model and provider separately through the revision-fenced `session.mutate` operation. The switch is refused if the owner cannot be resolved or focus changes while the request is in progress. Session selections, including an explicit `io` selection, use the durable stored-session ID; the live switch uses the runtime session ID. Foreign-profile chats must be managed from their owning profile.

---

## Multiple API Keys & Client Billing (Model Aliases)

Need to route Bonzai API costs to specific client accounts (e.g. Landal, Heineken)? You can set up named **client aliases** to switch seamlessly inside any chat session.

### Option A: Via the Setup Wizard (Recommended)

Run `python install.py --add-alias` (or select Option 2 in `Install-Bonzai-Model-Provider.command` / `.cmd`):

```text
====================================================
  🌿 Add a Client-Specific Bonzai Alias
====================================================
Client name (e.g. landal, heineken): landal
Paste the Bonzai API Key for 'landal': sk-bonzai-landal-...
Preferred model [gemini-3.7-flash]: gemini-3.7-flash

✅ Client alias 'landal' added!
```

### Option B: Directly in Hermes Chat

You can also configure client keys directly in your chat:

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
       label: Landal          # optional, shown in the Key Manager
   ```
3. Switch anytime in chat:
   ```text
   /model landal
   /model io
   ```

---

## Upgrading from a Previous Version

If you or your colleagues already have an older version of the Bonzai plugin installed:

- **Simply run the installer again.** The current installer is safe to run over an existing installation.
- It replaces the plugin files, preserves existing API keys and configuration, and detects whether your Hermes version natively resolves model-provider plugins.
- On current Hermes versions, it removes the old `HermesOverlay` workaround from Hermes-owned source. This is important because that source file can be replaced by a Hermes update.
- On older Hermes versions, the installer keeps the compatibility fallback.
- If an existing key is detected, the installer gives you the option to keep it, assign it to a client alias, or replace it.
- Restart Hermes Desktop after updating.

### Update checklist for colleagues

1. Update Hermes Desktop first. This maintenance release was verified against Hermes 0.23.2; legacy installation compatibility does not guarantee every Desktop key-management API on older builds.
2. Download and extract a fresh ZIP from the link above, or run `git pull --ff-only` in your existing checkout.
3. Run the macOS `.command` or Windows `.cmd` launcher. Choose **Install / Update Bonzai**, then **Keep as default iO key** when prompted for an existing key. Existing client keys and model selections are preserved.
4. Quit Hermes Desktop completely and reopen it.
5. In **Capabilities → Plugins**, keep both entries enabled: `bonzai-key-manager` (**General / User**, backend v2.1.0) and `Bonzai Key Manager` (**Desktop / Disk**, UI). A previously disabled Desktop toggle remains off until you enable it manually; Auto-update On is a different setting.
6. Open **Bonzai: Select client key** from the command palette. Test key switching in a short chat: default → client → default. The selected model should stay unchanged. **Selected** identifies your recorded choice, not verified billing; a chat without an explicit choice can still show **Key unverified**.

Do not paste API keys into a chat or send screenshots containing unmasked keys. The installer does not replace an existing model default with Luna 6.0; that default applies only to a fresh setup.

### Quick fix for colleagues

**macOS / Linux**, for a fresh or broken installation:

```bash
tmp_dir="$(mktemp -d)" && git clone --depth 1 https://github.com/maavangent/bonzai-hermes-plugin "$tmp_dir/bonzai-hermes-plugin" && cd "$tmp_dir/bonzai-hermes-plugin" && python3 install.py --interactive; status=$?; rm -rf "$tmp_dir"; exit $status
```

For an existing local checkout:

```bash
git pull --ff-only && python3 install.py --interactive
```

Then restart Hermes Desktop, or run `hermes gateway restart`. The installer does not repair a Bonzai-side HTTP 500 caused by invalid upstream Vertex credentials. That requires the Bonzai service team to fix the Vertex configuration.

---

## What the Installer Does

`install.py` handles the plumbing automatically:

1. Copies the provider into `~/.hermes/plugins/model-providers/bonzai/` (auto-discovered by Hermes).
2. Copies and enables the backend at `~/.hermes/plugins/bonzai-key-manager/`.
3. Copies the Desktop companion to `~/.hermes/desktop-plugins/bonzai-key-manager/plugin.js`.
4. On current Hermes versions, removes the legacy `HermesOverlay` patch from Hermes-owned source if an older install left it. Only Hermes versions without native provider-plugin resolution still get the overlay.
5. Sets Bonzai and Luna 6.0 (`gpt-6-luna`) for a fresh model configuration, but preserves an existing provider/model selection. Use `/model io` to select Bonzai when another provider is active.
6. Sets up the default `io` model alias in `config.yaml`.
7. Clears the model cache so newly added models appear immediately.

Run it with Hermes' own Python (the launchers detect `.venv` and legacy `venv`) so `config.yaml` edits keep your comments and formatting. Invalid configuration or missing PyYAML stops installation before existing plugin files are replaced. Keys in `.env` are written atomically with owner-only permissions and prompted without terminal echo. Moving an existing default key to a client requires a different replacement default key; cancelling leaves the original setup unchanged.

It honors the `HERMES_HOME` environment variable and falls back to `~/.hermes`.

---

## Health Check & Troubleshooting

Run a diagnostic check at any time:

```bash
python install.py --check
```

Reports whether the provider entrypoint/manifest, native-resolution source contract (or the legacy overlay on old Hermes versions), Key Manager backend, Desktop companion, and API key are configured. It also fails when client keys are still in the Bonzai credential pool, or when installed code/manifests differ from your checkout. This is an installation/configuration check, not a live API-key validation or proof of a working completion.

---

## Uninstall

To completely remove the Bonzai plugin, overlay, Desktop companion, and model cache:

```bash
python install.py --uninstall
```

Restart Hermes afterwards.

---

## Which Models You See

- **Picker ordering follows the current curated rule.** Live Bonzai aliases lead in the requested order. Claude stays grouped by subtype; numeric model versions descend within each Claude/Gemini/GLM family. GPT versions descend numerically by model track, with Luna before Sol when versions tie. The newest three recognized releases are retained; GPT-4, O-series, lightweight and unclassified IDs are omitted. Other recognized families follow.

The provider returns only real, selectable model IDs. Hermes has no provider-level non-selectable divider row, so the plugin doesn't add fake IDs. Search remains available with **CMD+SHIFT+M**.

- **Alias order:** `bonzai-executor`, `bonzai-analyst`, `bonzai-explorer`, `bonzai-architect`, when present.
- **GPT-6 and GPT-5** are ordered newest generation first, by version within each track, with Luna before Sol on ties. The base generation ID stays distinct if Bonzai returns one.
- Alias targets are not hardcoded; Bonzai can reroute them server-side.

**Also filtered out:** non-chat endpoints, compliance-bypassing IDs, backend/region/date duplicates, duplicate Claude naming schemes, lightweight variants, GPT-4, O-series, and unclassified IDs. The plugin doesn't rewrite catalog model IDs.

Successful fetches and validated metadata snapshots are cached atomically in `$HERMES_HOME/bonzai_models_cache.json` for offline resilience, bound to the current profile and credential fingerprint. Refresh Models clears the in-process memo. An older unbound cache needs one successful online fetch after upgrading. Credential-specific catalog limits are not copied into Hermes' singleton provider metadata: the current request-sizing hook receives a model but no credential. Request caps therefore use declared provider-wide limits and measured static exceptions until a credential-aware SDK contract is available.

On Hermes Desktop 0.2.7 and newer, the Key Manager can resolve the focused chat's owning connection/profile and route a live model switch through that owner. Stored key bindings stay in the active profile; to manage a chat from another profile, switch Hermes Desktop to that profile first. Older Desktop versions fail closed if owner routing is unavailable.

`GET /sessions` exposes only sessions stored in the active profile. It does not enumerate other profiles through another gateway. The session key is read from `GET /config` for the active profile.

The Key Manager backend avoids Hermes' profile-scoped numbered environment-key scan, which can raise `UnscopedSecretError` in multiplexed dashboard RPCs.

---

## Repo map

| File | Purpose |
|---|---|
| `bonzai/__init__.py` | Hermes provider and live model catalog |
| `install.py` | Cross-platform install, upgrade, check, alias and uninstall commands |
| `key-manager/dashboard/plugin_api.py` | Secret-safe Key Manager API |
| `key-manager/desktop/plugin.js` | Hermes Desktop Key Manager extension and key switches |
| `CHANGELOG.md` | Provider and Key Manager release history |
| `docs/plans/2026-10-08-picker-and-session-key-analysis.md` | Picker and session-key implementation evidence and verification |
| `tests/test_shortlist.py` | Ordering and filter regression tests |

## Verification

Run the complete test suite from the repository root with:

```bash
uv run --with-requirements requirements-test.txt --python 3.11 pytest -q
```

The JavaScript companion checks run in the pytest suite and require Node.js. `uv run` creates an isolated environment for the test command. Install the same test dependencies in a virtual environment with `python -m pip install -r requirements-test.txt`.

Stateful Desktop behavior tests require Node.js >=22.12 and React/ReactDOM/jsdom. Install the pinned test dependencies with `npm ci --prefix tests/js` (the harness can also reuse Hermes Desktop's installed dependencies). Set `HERMES_SDK_SOURCE` to your Hermes source checkout if it is not at `~/.hermes/hermes-agent`; the harness validates the SDK methods against that source. These are mocked-transport React/DOM tests, not a live Electron or Bonzai completion test.

---

## License

MIT © iO Digital / Maarten van Gent
