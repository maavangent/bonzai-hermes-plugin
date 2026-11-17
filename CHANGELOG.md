# Changelog

## Provider 2.11.0 / Key Manager 2.1.0 (2026-11-17)

- Fresh installations default to Luna 6.0 (`gpt-6-luna`); existing model selections remain unchanged.
- Key switches preserve the current chat model (configured Hermes default when absent) using stable named client endpoints rather than changing legacy aliases. Explicit default selections display `Selected · iO (Default)` consistently with client selections; neither label claims verified billing identity.

- Client-key switching uses the SDK's `session.model` adapter rather than the retired `config.set model` shape. Tests reproduce the canonical gateway's `use_session_mutation_model` refusal.

- Provider releases sort as integer tuples, including versions such as 6.10.
- Refresh invalidates plugin-local caches; offline catalog and metadata are written atomically and bound to the profile and credential fingerprint. Old unbound caches require one successful online fetch.
- Credential-specific catalog snapshots no longer mutate singleton provider capabilities or leak limits to another profile/key. Request sizing uses declared provider-wide limits and measured static exceptions; dynamic per-credential sizing awaits a credential-aware SDK hook. The provider-scoped Gemini context correction survives catalog updates. Credential-bearing catalog/key-test requests use safe redirect handling.
- Installer preflights configuration before file removal, discovers `.venv`, preserves another provider's model selection, hides key input, and requires a different replacement default key before moving the old key to a client.
- Health checks reject missing keys/entrypoints and stale manifests; launchers preserve installer exit status.
- Key Manager mutations are serialized across read/modify/write, verify alias persistence, roll back a new secret when alias saving fails, reject orphan-secret collisions, and retain distinct legacy keys with identical labels.
- Removing a key selected in a chat is refused. Selecting an unknown or unconfigured client alias is refused. The backend never uses another profile's ambient default key.
- Test dependencies include the current Hermes config-writer dependencies; provider SDK stubs are scoped to each import instead of leaking into other test files.
- Desktop actions check the owning profile at invocation, Save & Use keeps the original chat identity, and key inputs clear on profile change. Rename/Test controls and a real palette-open action reuse the SDK. Stateful React/DOM tests cover rerenders and event cleanup.
- Session status no longer invents an active billing identity from an advisory selection. Owner-routed session information reports inactive/unknown/unverified status; the core API lacks authoritative credential identity.
- Key switches are idle-only. Unexpected deferred selections remain explicitly pending with alias-only local persistence and require idle reselection; stored-session mismatches are rejected. JavaScript behavior dependencies are pinned for reproducible runs.

Configured Hermes fallback chains are not a strict credential pin; the plugin does not change Hermes core or guarantee billing isolation across fallback providers. Verification: 222 tests passed, 1 skipped; live switching confirmed by Maarten in a short session. Windows remains statically tested, not live-tested.

## Bonzai provider 2.10.0

The latest released Bonzai provider is **2.10.0**. Provider and installer changes are included here. The Key Manager backend/dashboard remain at **2.0.0**; no Key Manager UI changes are part of this release. Hermes Desktop core model-picker changes are separate and not included here.

### Fixed

- **Profile secret reads stay fail-closed.** A scoped-secret lookup error no longer triggers an unscoped process-environment fallback. Standalone development still falls back if Hermes' secret-scope module is absent.
- **Client alias collisions are rejected before secrets are written.** Adding a duplicate alias no longer overwrites the existing key or alias configuration.
- **Session-key JSON writes remain atomic.** Added regression coverage for atomic replacement and temporary-file cleanup.

### Changed

- **Compact picker order is version-aware.** Bonzai aliases lead in the requested order. GPT tracks sort numerically, Luna before Sol on a tie. Claude/Gemini/GLM are grouped by subtype/family, newest first. The compact list keeps the latest three recognized releases; it omits GPT-4, O-series, lightweight and unclassified IDs, other duplicates and non-chat endpoints. Only real Bonzai catalog IDs are returned; model IDs and live alias targets are not rewritten or pinned.

### Documentation

- README documents current model filtering, the lack of provider-level non-selectable divider rows, profile-secret safety, installation behavior and a reproducible test command.
- Added a checked-in isolated test dependency list and updated picker/session implementation notes with verified results and remaining limits.

## Earlier Key Manager changes (v2.0.0)

The separate Key Manager package introduced these safety changes. They are not part of provider version 2.10.0.

- **Client keys stay isolated from Bonzai pool rotation.** Client keys are stored as a `.env` secret plus a `model_aliases` entry; Key Manager 2.0 migrates older manual pool rows on first use. An existing alias or hand-edited `.env` value wins over a pool copy.
- **Key switches are checked before recording a binding.** `config.set model <alias> --session` reports rejected and deferred switches accurately.
- **Status warns for removed keys.** Removing a key clears its chat bindings and secret unless another alias shares that secret.
- **Installer avoids corrupting `config.yaml`.** It requires a YAML parser for config edits and uses Hermes' comment-preserving writer when available.
- **`.env` writes are atomic and owner-only (0600)**, recognise `export KEY=` lines, and drop duplicate definitions.
- **Installer and Key Manager derive the same alias name** for a client (`Landal NL` → `landal-nl`) and reject reserved names such as `io`.
- **Model list cache is scoped per key and profile.** A Hermes process serving several profiles does not reuse another profile's catalog. Default secrets are read through Hermes' profile scope.
- **Windows launcher** prefers the `py` launcher over a bare `python`.
- **Gemini 3.7 Flash context metadata** works around historical Bonzai context metadata drift via native Hermes `model_capabilities`.
- **Hermes update compatibility:** Provider installation uses Hermes' native registered-provider resolution on Hermes 0.22.0 and newer; older versions use the compatibility overlay.
- Conservative output-token caps, provider-specific Bonzai/Vertex gateway error classification and scoped dashboard secret reads are covered by tests.

## Notes from earlier provider releases
