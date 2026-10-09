# Changelog

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
