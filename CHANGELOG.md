# Changelog

## Unreleased

### Fixed

- Stop injecting the legacy `HermesOverlay` into Hermes-owned `providers.py` when the installed Hermes version natively resolves registered model-provider profiles.
- Remove an old Bonzai overlay automatically when upgrading on a Hermes version with native provider resolution. This prevents a later Hermes update from silently removing the provider workaround and breaking Bonzai.
- Keep the overlay fallback for older Hermes versions that still need it.
- Add installer regression coverage for native provider resolution and legacy overlay cleanup.

### Documentation

- Documented the safe colleague recovery command and the difference between a local plugin installation failure and a Bonzai-side HTTP 500.

### Known issue

A Bonzai HTTP 500 can still originate in the Bonzai service backend. On 23 September 2026, the observed error was a Vertex credential JSON parse failure upstream of Hermes. Reinstalling the plugin cannot repair malformed Bonzai-side Vertex credentials.
