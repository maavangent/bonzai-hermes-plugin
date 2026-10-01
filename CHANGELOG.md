# Changelog

## Unreleased

### Fixed

- **Client keys could bill the wrong account (Key Manager 2.0).** Client keys added in the Desktop Key Manager were stored in Hermes' Bonzai credential pool. Hermes rotates pool keys automatically after a 429 or a rejected key, so iO work could continue on a client key without any visible switch, and the reverse. Client keys are now stored only as a `.env` secret plus a `model_aliases` entry, which pool rotation cannot reach. Keys from older versions are migrated out of the pool the first time Desktop loads the Key Manager; an existing alias or hand-edited `.env` value always wins over the pool copy.
- **Key switch reported success when Hermes refused it.** The Desktop companion called `slash.exec`, which returns success with only a warning when `/model` fails or the chat is busy, and it stored the chat's key before the switch ran. It now uses `config.set model <alias> --session`, the RPC the Desktop model picker uses: a refused switch shows an error and stores nothing, and a switch made during a reply is reported as taking effect after that reply.
- **Status chip showed a removed key as active.** A chat bound to a deleted key now shows a warning dot and a prompt to pick another key. Removing a key also clears its chat bindings and its `.env` secret, unless another alias still uses that secret.
- **Installer could corrupt `config.yaml` without PyYAML.** The hand-written fallback parser flattened nested sections and wrote the damage back. The installer now refuses to touch `config.yaml` without a YAML parser, and uses Hermes' own comment-preserving writer when it runs in Hermes' Python.
- **`.env` writes are atomic and owner-only (0600)**, recognise `export KEY=` lines, and drop duplicate definitions.
- **Installer and Key Manager now derive the same alias name** for a client (`Landal NL` → `landal-nl`), reject reserved names such as `io`, and the wizard prints the alias that was actually created.
- **Model list cache is scoped per key and profile.** One Hermes process serving several profiles no longer returns a catalog fetched with another profile's key. The default key is read through Hermes' per-profile secret scope.
- **Windows launcher** prefers the `py` launcher over a bare `python`, which can be the Microsoft Store stub.
- **Gemini 3.7 Flash context metadata:** Bonzai's `/v1/models` endpoint reported `4,096`, although the upstream model documents a `1,048,576`-token context window. The provider declares that capability through Hermes' native `model_capabilities` metadata so Hermes' 64K startup gate does not reject new sessions. (Bonzai's catalog reports the correct value again as of 27 September 2026; the override stays as a floor.)
- Stop injecting the legacy `HermesOverlay` into Hermes-owned `providers.py` when the installed Hermes version natively resolves registered model-provider profiles.
- Remove an old Bonzai overlay automatically when upgrading on a Hermes version with native provider resolution. This prevents a later Hermes update from silently removing the provider workaround and breaking Bonzai.
- Keep the overlay fallback for older Hermes versions that still need it.
- Add installer regression coverage for native provider resolution and legacy overlay cleanup.
- **Output-token probe:** all 40 models in the current shortlist accepted a `max_tokens=32768` probe request. The provider keeps conservative catalog-derived caps for `gpt-4o` and `gpt-4o-mini`, whose metadata reports a 16,384 output limit.

- **Capability probes:** all 40 shortlisted models accepted harmless tool-schema and 1×1 image probes. Bonzai is now marked as vision-capable at provider level; tool support remains Hermes' default for chat models.
- Provider-specific Bonzai/Vertex gateway 500s are classified separately from local authentication failures, with secret-free recovery context.
- The Key Manager dashboard avoids Hermes' profile-scoped numbered environment-key scan, which can raise `UnscopedSecretError` in multiplexed dashboard RPCs.

### Changed

- **gpt-6 family recognised in the model shortlist.** `gpt-6`, `gpt-6.N`, and named variants (`gpt-6-luna`, `gpt-6-sol`) are now treated as flagship chat models and promoted to tier-1 in the model picker. Lightweight variants (`gpt-6-mini`) remain in tier-2.
- **Hermes version check in `--check`.**  Running `python install.py --check` now reports whether the installed Hermes version supports `classify_api_error` (requires Hermes >= 0.21.0). Older builds load-fail with `ProviderProfile.__init__() got an unexpected keyword argument 'classify_api_error'`; the check flags this before it becomes a silent failure for a colleague.
- **`default_aux_model` documented.** Inline comment added noting that `claude-haiku-4-5` should be re-probed after each Haiku release.

### Documentation

- Documented the safe colleague recovery command and the difference between a local plugin installation failure and a Bonzai-side HTTP 500.
- README: why client keys stay out of the credential pool, per-chat switching behaviour, the real palette command, and the native (overlay-free) install path.

### Removed

- Key Manager `/strategy` and `/credentials/reset` endpoints. They only configured pool rotation for client keys, which no longer exists. The Desktop companion never called them.

### Tests

- Desktop companion tests now run the real `plugin.js` in Node with a stubbed SDK and assert the calls it makes, instead of searching its source text.
- Regression test proving a rate-limited default key has no client key to rotate onto, and an E2E check that Hermes' alias resolver hands `/model <alias>` the client key.

### Known issue

A Bonzai HTTP 500 can still originate in the Bonzai service backend. On 23 September 2026, the observed error was a Vertex credential JSON parse failure upstream of Hermes. Reinstalling the plugin cannot repair malformed Bonzai-side Vertex credentials.

The `classify_api_error` plugin kwarg requires Hermes >= 0.21.0. On older builds the plugin fails to load at startup with `ProviderProfile.__init__() got an unexpected keyword argument 'classify_api_error'`. Fix: `hermes update`.
