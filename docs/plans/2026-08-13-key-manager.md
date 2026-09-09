# Bonzai Key Manager Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Modernize the Bonzai model-provider plugin and add a safe Desktop companion for managing Bonzai credentials through Hermes' existing credential pool.

**Architecture:** Keep the specialized model-provider under `plugins/model-providers/bonzai`. Add a separate enabled general plugin `bonzai-key-manager` with a profile-aware FastAPI backend and a local Desktop SDK `plugin.js`. The backend alone touches credential pools; the renderer receives metadata and never receives stored secrets. Per-session credential pinning remains out of scope until Hermes exposes a generic public API.

**Tech Stack:** Python 3.11, pytest, Hermes ProviderProfile and CredentialPool APIs, FastAPI APIRouter, plain ESM Hermes Desktop SDK.

---

### Task 1: Provider cleanup

**Files:**
- Modify: `bonzai/__init__.py`
- Modify: `bonzai/plugin.yaml`
- Modify: `tests/test_shortlist.py`
- Modify: `tests/test_installer.py`
- Modify: `install.py`
- Modify: legacy shell scripts

**Behavior:** Return only real model IDs; add manifest v2 metadata; make overlay installation and update fail closed; resolve shared Hermes source independently of profile home; keep legacy scripts as thin wrappers only.

**Verification:** Targeted pytest in RED/GREEN cycles, full test suite, compileall, install check, provider inventory.

### Task 2: Key-manager backend

**Files:**
- Create: `key-manager/plugin.yaml`
- Create: `key-manager/__init__.py`
- Create: `key-manager/dashboard/manifest.json`
- Create: `key-manager/dashboard/plugin_api.py`
- Create: `tests/test_key_manager_api.py`

**Behavior:** List secret-free credential metadata; add/test/remove/rename manual Bonzai keys; reset cooldowns; read/write the Bonzai pool strategy. Environment-backed credentials are visible but not removable or renameable through this plugin. Never return access tokens.

**Verification:** API helper tests against an isolated `HERMES_HOME`, including response secret scan and invalid-input/error paths.

### Task 3: Desktop companion

**Files:**
- Create: `key-manager/desktop/plugin.js`
- Create/update: installer tests and README

**Behavior:** Appear in Settings → Plugins, show a Bonzai-only statusbar chip, open a compact manager pane, list labels/status, add via masked input, test, rename/remove manual entries, reset cooldowns, choose rotation strategy, and expose command-palette actions. Do not claim per-session pinning; explain Automatic Rotation and mark pinning as unavailable until the generic Hermes API exists.

**Verification:** Install into the active profile, enable Python plugin, load Desktop plugin, inspect runtime inventory/logs and exercise backend calls. Use only SDK imports and plain `jsx()`/`jsxs()`.

### Task 4: Integration and documentation

**Files:**
- Modify: `install.py`
- Modify: `README.md`
- Modify: Obsidian project note after verified execution

**Behavior:** One installer deploys both halves, enables the key-manager backend, preserves the temporary overlay workaround, and clearly separates built functionality from deferred session pinning.

**Verification:** Clean install/check, all tests, Hermes Doctor, live Bonzai model fetch and one real completion, independent spec and quality review.
