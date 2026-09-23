# Changelog

## Unreleased

### Fixed

- **Gemini 3.7 Flash context metadata:** Bonzai's `/v1/models` endpoint currently reports `4,096`, although the upstream model documents a `1,048,576`-token context window. The provider declares that capability through Hermes' native `model_capabilities` metadata so Hermes' 64K startup gate does not reject new sessions.
- Stop injecting the legacy `HermesOverlay` into Hermes-owned `providers.py` when the installed Hermes version natively resolves registered model-provider profiles.
- Remove an old Bonzai overlay automatically when upgrading on a Hermes version with native provider resolution. This prevents a later Hermes update from silently removing the provider workaround and breaking Bonzai.
- Keep the overlay fallback for older Hermes versions that still need it.
- Add installer regression coverage for native provider resolution and legacy overlay cleanup.
- **Output-token probe:** all 40 models in the current shortlist accepted a `max_tokens=32768` probe request. The provider keeps conservative catalog-derived caps for `gpt-4o` and `gpt-4o-mini`, whose metadata reports a 16,384 output limit.

- **Capability probes:** all 40 shortlisted models accepted harmless tool-schema and 1×1 image probes. Bonzai is now marked as vision-capable at provider level; tool support remains Hermes' default for chat models.
- Provider-specific Bonzai/Vertex gateway 500s are classified separately from local authentication failures, with secret-free recovery context.
- The Key Manager dashboard avoids Hermes' profile-scoped numbered environment-key scan, which can raise `UnscopedSecretError` in multiplexed dashboard RPCs.

### Documentation

- Documented the safe colleague recovery command and the difference between a local plugin installation failure and a Bonzai-side HTTP 500.

### Known issue

A Bonzai HTTP 500 can still originate in the Bonzai service backend. On 23 September 2026, the observed error was a Vertex credential JSON parse failure upstream of Hermes. Reinstalling the plugin cannot repair malformed Bonzai-side Vertex credentials.
