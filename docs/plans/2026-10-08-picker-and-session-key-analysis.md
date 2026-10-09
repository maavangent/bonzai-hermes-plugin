# Bonzai picker and session key implementation notes

This note records the current picker and Key Manager behavior, why the picker excludes fake dividers, and what still needs a live Desktop check. Historical plans and catalog probes are labeled as such; consult the README for the current user-facing rules.

**Architecture:** Keep the Bonzai model catalog live and model IDs untouched. Only emit real selectable IDs. Route model switches through the focused session's owning Desktop connection/profile, but keep saved key bindings local to the active profile because the backend REST API does not proxy foreign profiles. Do not infer a client's active billing key from a resolved model target alone: multiple aliases may share one target.

**Tech stack:** Python provider plugin, pytest, Hermes Desktop plugin SDK (ESM JavaScript), Node behavior harness.

---

## Evidence and decisions

- A live Bonzai `/v1/models` probe returned 124 IDs. This was a point-in-time diagnostic from October 2026, not a release acceptance threshold or a claim about the latest catalog.
- Hermes' provider contract is a flat list of selectable model IDs. A fake Unicode divider can be accepted as an unknown model when `/models` lookup fails, so the provider returns no divider sentinel.
- Hermes Desktop exposes `focusedSessionOwner`, `focusedStoredSessionId`, `profileRoutes`, and `requestProfile`. Its plugin REST API follows the active profile and has no owner-route option. Live model changes can follow the owner route; stored key bindings remain scoped to the active profile. Client labels may be ambiguous if `session.info.model` reports a shared resolved target.

Historical smoke test: 51 catalog IDs, 50 vision probes passed. The catalog changes, so current usability is not inferred from that old count.

## Current behavior summary

- Bonzai alias order: Executor, Analyst, Explorer, Architect. Backing model IDs are server-managed and never hardcoded.
- Claude subtypes and Gemini/GLM versions sort newest first. GPT tracks sort by numeric release, Luna before Sol on ties. Only the three newest recognized release buckets are retained in each supported family.
- Non-chat endpoints, compliance-bypass IDs, duplicate Claude spellings, GPT-4, O-series, lightweight and unclassified models are omitted.
- The provider emits only real model IDs; separators require a native non-selectable model-row contract in Hermes Desktop.

## Implementation and regression tests

- `bonzai/__init__.py`: live aliases and compact provider shortlist with real catalog IDs.
- `tests/test_shortlist.py`: ordering, real-ID, filter, alias and release-bucket tests.
- `install.py` and `tests/test_installer.py`: alias conflict prevention, config safety and install regression tests.
- `tests/test_offline_cache.py`: profile-specific secret scope and model-cache tests.
- `key-manager/dashboard/plugin_api.py` and `tests/test_key_manager_api.py`: active-profile key store, locks and atomic replacement.
- `key-manager/desktop/plugin.js` and `tests/test_desktop_plugin_contract.py`: owner-routed key switching with fail-closed behavior tests.
- Provider manifest version: **2.10.0**. Key Manager backend and dashboard remain at **2.0.0**.


**Historical design, superseded:** The original plan grouped aliases, latest/previous buckets and a remainder tier. Current behavior is described in the README and tests below.

1. Separate the four live Bonzai aliases in the agreed order; never pin their backing model targets.
2. Sort Claude subtypes and descending version, with the analogous numeric ordering for Gemini and GLM. Group GPT tracks by numeric version and rank Luna ahead of Sol when versions tie.
3. Promote only the latest three recognized releases in the compact picker; omit GPT-4, O-series, lightweight and unclassified entries. Keep all emitted IDs real and unchanged.
4. Preserve duplicate removal and filtering for non-chat endpoints, compliance bypasses, backend/region/date duplicates and duplicate Claude spellings.
5. Run `uv run --with-requirements ... pytest -q tests/test_shortlist.py tests/test_offline_cache.py` against the actual current implementation.

**Verified implementation:** tests assert latest three release buckets and filter-out cases. No fake IDs or pinned alias targets are included.

---
## Key Manager routing implemented

- Key switching records the focused runtime session ID, durable stored-session ID and owner connection/profile. It resolves exactly one route for that owner, then rechecks identity before and after the routed RPC. Missing or ambiguous owner routes and focus changes abort the operation.
- The live model update is routed to the focused session owner. The saved binding uses the stored-session ID via the local REST API only when the focused owner matches that API's active profile.
- A chat in another profile cannot use this panel to read or mutate that profile's stored keys. The panel asks the user to open the chat's owning profile rather than showing a false default.
- Automated behavior tests cover local and foreign owner routes, unresolved/ambiguous routes, and focus changes during route lookup and RPC.



## Deferred design work

### Deferred alias status identity

**Files:**
- Inspect Hermes current alias resolution and `session.info` contract
- Modify only if verified: `key-manager/dashboard/plugin_api.py`, `key-manager/desktop/plugin.js`

**Steps:**
1. Reproduce how configured `model_aliases` appear in `session.info` after both immediate and deferred switches. Hermes may report the alias label or the resolved target model; prove which shape occurs for `model_aliases` entries with `provider: custom`, `base_url`, and `key_env`.
2. If `session.info.model` is the alias, label it directly. If it is the target, ask Hermes' resolver/backend for the resolved alias name or provide a secret-safe, profile-scoped reverse map from persisted `config.yaml`; do not infer a client key from the model alone when two aliases can share a target.
3. Verify `bonzai-analyst`, `bonzai-executor`, etc. are not confused with client billing aliases. Bind only configured Bonzai client aliases (`key_env` + Bonzai URL) to names.
4. Add tests for two client keys sharing a target model, alias rename/remove, missing key_env secret, default iO route, and a Bonzai suggestion alias that has no account-specific credential.

### Deferred live-state reconciliation

**Objective:** Avoid stale status chips after session switches, model-picker changes, deferred switches, or switches made outside the key manager.

**Files:**
- Modify: `key-manager/desktop/plugin.js`, `key-manager/dashboard/plugin_api.py` only if a safe backend migration is needed
- Test: `tests/js/run_plugin.mjs`, `tests/test_desktop_plugin_contract.py`, relevant backend tests

**Steps:**
1. Add tests for external model switch, `session.info` updates, session runtime-ID rebuild, deferred selection, rejected selection, and focus changes while an async “Save & Use” is in progress.
2. Subscribe with tracked `ctx.onEvent('session.info', …)` and filter by owning connection/profile and session identity. Keep React Query invalidation as fallback, not a 5-second poll as the primary signal.
3. Distinguish pending/deferred alias choice from alias currently in effect. Do not display “active” until Hermes confirms the session's actual model/provider has changed.
4. Derive the displayed key from Hermes' authoritative session model/route when possible. If the alias→credential label still needs plugin metadata, reconcile it against that route rather than trusting an unvalidated independent binding.
5. Validate assigned slugs against configured aliases server-side and make alias deletion/binding cleanup safe under concurrent requests.
6. Run focused behavior/API tests, then full suite.

## Release scope

Provider 2.10.0 changes are summarized in `CHANGELOG.md`. The Key Manager 2.0.0 package includes the profile-aware extension behavior in this repository. Hermes Desktop core model-picker changes, if any, are separate and not included here.

## Release verification

- `uv run --with-requirements requirements-test.txt --python 3.11 pytest -q`: **116 passed, 1 skipped**.
- `node --check key-manager/desktop/plugin.js` and `node --check tests/js/run_plugin.mjs`: passed.
- `python3 -m py_compile bonzai/__init__.py install.py key-manager/dashboard/plugin_api.py`: passed.
- `git diff --check`: passed.
- `python3 install.py` installed this checkout; `python3 install.py --check` returned exit 0. Provider and Desktop companion files matched the checkout; installed companion passed the behavior harness.
- `hermes gateway restart` did not return within the command timeout. No gateway restart or real billing-route smoke test is claimed; restart Hermes Desktop before exercising live behavior.

## Remaining limitations

- **Owner routing:** live config/model switches use the Desktop owner's route. Key bindings and credential operations through the backend REST API remain profile-scoped to the current profile, intentionally. A foreign-profile chat cannot be managed from the wrong profile's panel.
- **Alias status:** `session.info.model` may expose a resolved target rather than the alias. Multiple client aliases can share a target, so do not derive the key label from a target alone. The UI should surface binding state without implying verification of active billing identity.
- **Verification still needed:** exercise live model switching with two real profiles and separate client-key sessions in Hermes Desktop. Automated tests cover the routing decision and fail-closed cases, not gateway-to-provider billing end to end.
