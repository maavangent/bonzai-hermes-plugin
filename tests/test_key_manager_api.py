from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient


REPO = Path(__file__).resolve().parents[1]
HERMES_SOURCE = Path.home() / ".hermes" / "hermes-agent"
API_PATH = REPO / "key-manager" / "dashboard" / "plugin_api.py"
BONZAI_URL = "https://api-v2.bonzai.iodigital.com"


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("BONZAI_API_KEY", "env-super-secret")
    (tmp_path / ".env").write_text("BONZAI_API_KEY=env-super-secret\n")
    (tmp_path / ".env").chmod(0o600)
    before = set(os.environ)
    sys.path.insert(0, str(HERMES_SOURCE))
    try:
        spec = importlib.util.spec_from_file_location("bonzai_key_manager_api", API_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        app = FastAPI()
        app.include_router(module.router)
        yield module, TestClient(app), tmp_path
    finally:
        sys.path.remove(str(HERMES_SOURCE))
        sys.modules.pop("bonzai_key_manager_api", None)
        # save_env_value publishes to os.environ; keep tests independent.
        for name in set(os.environ) - before:
            os.environ.pop(name, None)


def _config(home: Path) -> dict:
    path = home / "config.yaml"
    return (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}


def _env(home: Path) -> str:
    path = home / ".env"
    return path.read_text() if path.is_file() else ""


def _pool_rows(home: Path) -> list:
    path = home / "auth.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text()).get("credential_pool", {}).get("bonzai", [])


def test_list_returns_secret_free_default_key(api):
    _module, client, _home = api

    payload = client.get("/credentials").json()

    assert payload["migrated"] == 0
    assert payload["credentials"] == [{
        "id": "io",
        "slug": "io",
        "label": "iO (Default)",
        "kind": "default",
        "model": None,
        "masked": "env-su...cret",
        "configured": True,
        "removable": False,
        "renameable": False,
    }]
    assert "env-super-secret" not in json.dumps(payload)


def test_added_client_key_is_an_alias_and_never_a_pool_candidate(api):
    """Billing invariant: pool rotation must never reach a client key."""
    _module, client, home = api

    response = client.post("/credentials", json={"label": "Landal NL", "api_key": "landal-super-secret"})

    assert response.status_code == 201
    credential = response.json()["credential"]
    assert credential["slug"] == "landal-nl"
    assert credential["label"] == "Landal NL"
    assert "landal-super-secret" not in response.text
    assert _config(home)["model_aliases"]["landal-nl"] == {
        "model": "gpt-6-luna",
        "provider": "custom",
        "base_url": BONZAI_URL,
        "key_env": "BONZAI_LANDAL_NL_API_KEY",
        "label": "Landal NL",
    }
    assert "BONZAI_LANDAL_NL_API_KEY=landal-super-secret" in _env(home)
    assert _pool_rows(home) == []

    # Register the real provider so Hermes seeds its pool exactly as at runtime,
    # then prove a rate-limited default key has nothing to rotate onto.
    sys.path.insert(0, str(REPO))
    try:
        sys.modules.pop("bonzai", None)
        import bonzai  # noqa: F401
        from hermes_cli.auth import PROVIDER_REGISTRY, ProviderConfig
        PROVIDER_REGISTRY.setdefault("bonzai", ProviderConfig(
            id="bonzai", name="Bonzai", auth_type="api_key",
            inference_base_url=BONZAI_URL + "/", api_key_env_vars=("BONZAI_API_KEY",),
        ))
        from agent.credential_pool import load_pool
        pool = load_pool("bonzai")
        assert [entry.runtime_api_key for entry in pool.entries()] == ["env-super-secret"]
        assert pool.select().runtime_api_key == "env-super-secret"
        assert pool.mark_exhausted_and_rotate(status_code=429) is None
    finally:
        sys.path.remove(str(REPO))
        sys.modules.pop("bonzai", None)


def test_prepare_route_preserves_model_and_legacy_alias(api):
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret", "model": "legacy-model"})
    aliases = _config(home)["model_aliases"]
    response = client.post("/credentials/landal/route", json={"model": "gpt-6.1-sol"})
    assert response.status_code == 200
    assert response.json() == {"payload": {"model": "gpt-6.1-sol", "provider": "custom:bonzai-key-landal"}}
    assert _config(home)["model_aliases"] == aliases
    assert _config(home)["providers"]["bonzai-key-landal"] == {
        "name": "Bonzai key · landal", "api": BONZAI_URL,
        "transport": "chat_completions", "key_env": "BONZAI_LANDAL_API_KEY",
    }
    assert "landal-super-secret" not in response.text


@pytest.mark.parametrize("slug", ["io", "landal"])
def test_route_without_current_model_uses_configured_default(api, slug):
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})
    cfg = _config(home)
    cfg["model"] = {"default": "gpt-6-luna", "provider": "bonzai"}
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    response = client.post(f"/credentials/{slug}/route", json={})
    assert response.status_code == 200
    assert response.json()["payload"] == {
        "model": "gpt-6-luna", "provider": "bonzai" if slug == "io" else "custom:bonzai-key-landal",
    }


@pytest.mark.parametrize("slug", ["io", "landal"])
def test_route_refuses_raw_model_alias_collision_without_changing_config(api, slug):
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "synthetic-client"})
    cfg = _config(home)
    cfg["model_aliases"]["gpt-6.1-sol"] = {"model": "different-model", "provider": "bonzai"}
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    before = (home / "config.yaml").read_bytes()
    response = client.post(f"/credentials/{slug}/route", json={"model": "gpt-6.1-sol"})
    assert response.status_code == 409
    assert "alias" in response.json()["detail"]
    assert (home / "config.yaml").read_bytes() == before


def test_new_client_legacy_alias_uses_configured_model(api):
    _module, client, home = api
    (home / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "gpt-6.1-sol", "provider": "bonzai"}}))
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})
    assert _config(home)["model_aliases"]["landal"]["model"] == "gpt-6.1-sol"


def test_remove_cleans_only_its_prepared_endpoint(api):
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})
    client.post("/credentials/landal/route", json={"model": "gpt-6-luna"})
    assert client.delete("/credentials/landal").status_code == 204
    assert "bonzai-key-landal" not in _config(home).get("providers", {})


@pytest.mark.parametrize("fault", ["foreign", "refused", "missing-key"])
def test_route_preparation_fails_closed(api, monkeypatch, fault):
    module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})
    cfg = _config(home)
    if fault == "foreign":
        cfg["providers"] = {"bonzai-key-landal": {"api": "https://example.invalid"}}
        (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    elif fault == "refused":
        monkeypatch.setattr(module, "save_config", lambda cfg: None)
    else:
        (home / ".env").write_text("")
    response = client.post("/credentials/landal/route", json={"model": "gpt-6-luna"})
    assert response.status_code == 409
    assert client.get("/sessions").json()["sessions"] == {}


def test_remove_retains_secret_referenced_by_foreign_endpoint(api):
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})
    cfg = _config(home)
    cfg["providers"] = {"hand-edited": {"api": BONZAI_URL, "key_env": "BONZAI_LANDAL_API_KEY"}}
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    assert client.delete("/credentials/landal").status_code == 204
    assert "BONZAI_LANDAL_API_KEY=landal-super-secret" in _env(home)


def test_prepared_named_endpoint_resolves_with_real_hermes_runtime(api):
    """Run the actual Hermes interpreter/resolver in an isolated synthetic home."""
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "synthetic-landal-key"})
    payload = client.post("/credentials/landal/route", json={"model": "gpt-6.1-sol"}).json()["payload"]
    import subprocess
    python = HERMES_SOURCE / ".venv/bin/python"
    if not python.exists():
        pytest.skip("Actual Hermes interpreter unavailable")
    script = '''
import json, os
from pathlib import Path
import yaml
from hermes_cli.providers import resolve_provider_full
from hermes_cli.runtime_provider import frozen_runtime_config, resolve_runtime_provider
from hermes_cli.model_switch import switch_model, apply_model_selection
from hermes_cli import models_validate
cfg = yaml.safe_load((Path(os.environ['HERMES_HOME']) / 'config.yaml').read_text())
payload = json.loads(os.environ['TEST_PICK'])
from hermes_cli.config import get_compatible_custom_providers
custom = get_compatible_custom_providers(cfg)
pdef = resolve_provider_full(payload['provider'], cfg['providers'], custom)
assert pdef is not None, 'named provider missing'
assert pdef.source == 'user-config', pdef
# The external catalog/probe is the only substituted boundary: no network.
def validate(model, provider, **kwargs):
    assert model == payload['model']
    assert kwargs['api_key'] == 'synthetic-landal-key'
    assert kwargs['base_url'] == 'https://api-v2.bonzai.iodigital.com'
    return {'accepted': True, 'persist': True, 'recognized': True}
models_validate.validate_requested_model = validate
with frozen_runtime_config(cfg):
    runtime = resolve_runtime_provider(requested=payload['provider'], target_model=payload['model'])
    assert runtime['api_key'] == 'synthetic-landal-key'
    assert runtime['base_url'] == 'https://api-v2.bonzai.iodigital.com'
    result = switch_model(payload['model'], current_provider='custom:another-key',
                          current_model=payload['model'], current_api_key='synthetic-other-key',
                          current_base_url=runtime['base_url'], explicit_provider=payload['provider'],
                          user_providers=cfg['providers'], custom_providers=custom)
    assert result.success, result.message
    assert result.new_model == payload['model'] and result.api_key == 'synthetic-landal-key'
    selection = apply_model_selection({'default': payload['model'], 'provider':'custom:another-key',
                                      'api_key':'synthetic-other-key', 'key_env':'OTHER_KEY'}, result)
    assert selection['provider'] == payload['provider']
    assert 'api_key' not in selection and 'key_env' not in selection
print('real Hermes named-provider resolver and canonical switch passed; model preserved, old key cleared')
'''
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "HERMES_HOME": str(home),
           "PYTHONPATH": str(HERMES_SOURCE), "TEST_PICK": json.dumps(payload),
           "BONZAI_LANDAL_API_KEY": "synthetic-landal-key"}
    run = subprocess.run([str(python), "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert 'canonical switch passed' in run.stdout


def test_env_file_stays_private(api):
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})
    assert (home / ".env").stat().st_mode & 0o077 == 0


def test_added_key_resolves_through_hermes_alias_switch(api):
    """E2E through Hermes' own resolver: /model <alias> carries the alias key."""
    _module, client, _home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})

    from hermes_cli import model_switch
    model_switch.DIRECT_ALIASES.clear()
    model_switch._ensure_direct_aliases()
    alias = model_switch.DIRECT_ALIASES["landal"]

    assert alias.base_url == BONZAI_URL
    assert model_switch.direct_alias_api_key(alias) == "landal-super-secret"


@pytest.mark.parametrize("label", ["iO", "Default", "io", "Bonzai API key", "!!!"])
def test_add_rejects_reserved_or_empty_names(api, label):
    _module, client, home = api
    assert client.post("/credentials", json={"label": label, "api_key": "k"}).status_code == 422
    assert _config(home).get("model_aliases", {}) == {}


def test_add_refuses_to_overwrite_an_existing_alias(api):
    _module, client, home = api
    (home / "config.yaml").write_text(yaml.safe_dump({
        "model_aliases": {"landal": {"model": "llama3", "provider": "custom", "base_url": "http://localhost:11434"}},
    }))

    response = client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})

    assert response.status_code == 409
    assert _config(home)["model_aliases"]["landal"]["base_url"] == "http://localhost:11434"
    assert "landal-super-secret" not in _env(home)


@pytest.mark.parametrize("body", [
    {"label": "", "api_key": "valid"},
    {"label": "Work", "api_key": ""},
    {"label": "Work", "api_key": "  "},
])
def test_add_rejects_invalid_input(api, body):
    _module, client, _home = api
    assert client.post("/credentials", json=body).status_code == 422


def test_list_shows_only_bonzai_client_aliases(api):
    _module, client, home = api
    (home / "config.yaml").write_text(yaml.safe_dump({
        "model_aliases": {
            "io": {"model": "claude-sonnet-5", "provider": "bonzai"},
            "local": {"model": "llama3", "provider": "custom", "base_url": "http://localhost:11434"},
            "heineken": {
                "model": "claude-sonnet-5", "provider": "custom",
                "base_url": BONZAI_URL + "/", "key_env": "BONZAI_HEINEKEN_API_KEY",
            },
        },
    }))

    rows = client.get("/credentials").json()["credentials"]

    assert [row["slug"] for row in rows] == ["io", "heineken"]
    assert rows[0]["model"] == "claude-sonnet-5"
    assert rows[1] == {
        "id": "heineken", "slug": "heineken", "label": "heineken", "kind": "client",
        "model": "claude-sonnet-5", "masked": None, "configured": False,
        "removable": True, "renameable": True,
    }


def test_rename_changes_label_but_keeps_alias_and_secret(api):
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})
    client.post("/sessions/chat-1", json={"slug": "landal"})

    response = client.patch("/credentials/landal", json={"label": "Landal Parks"})

    assert response.status_code == 200
    assert response.json()["credential"]["label"] == "Landal Parks"
    alias = _config(home)["model_aliases"]["landal"]
    assert alias["label"] == "Landal Parks"
    assert alias["key_env"] == "BONZAI_LANDAL_API_KEY"
    assert client.get("/sessions/chat-1").json()["slug"] == "landal"
    assert client.patch("/credentials/landal", json={"label": "  "}).status_code == 422


def test_remove_refuses_a_key_bound_to_another_chat(api):
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})
    client.post("/sessions/chat-1", json={"slug": "landal"})

    response = client.delete("/credentials/landal")
    assert response.status_code == 409
    assert "chat" in response.json()["detail"]
    assert "landal" in _config(home)["model_aliases"]
    assert "landal-super-secret" in _env(home)
    assert client.get("/sessions/chat-1").json()["slug"] == "landal"


def test_remove_unbound_key_deletes_alias_and_secret(api):
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})
    assert client.delete("/credentials/landal").status_code == 204
    assert "landal" not in _config(home)["model_aliases"]
    assert "landal-super-secret" not in _env(home)


def test_default_does_not_read_another_profiles_ambient_key(api):
    _module, client, home = api
    (home / ".env").unlink()
    row = client.get("/credentials").json()["credentials"][0]
    assert row["configured"] is False
    assert row["masked"] is None
    assert client.post("/credentials/test-stored", json={"id": "io"}).status_code == 409


def test_remove_keeps_a_secret_that_another_alias_still_uses(api):
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})
    cfg = _config(home)
    cfg["model_aliases"]["landal-opus"] = dict(cfg["model_aliases"]["landal"], model="claude-opus-5-5")
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))

    assert client.delete("/credentials/landal").status_code == 204
    assert "BONZAI_LANDAL_API_KEY=landal-super-secret" in _env(home)


def test_default_key_and_foreign_aliases_are_protected(api):
    _module, client, home = api
    (home / "config.yaml").write_text(yaml.safe_dump({
        "model_aliases": {"local": {"model": "llama3", "provider": "custom", "base_url": "http://localhost:11434"}},
    }))

    assert client.patch("/credentials/io", json={"label": "Nope"}).status_code == 403
    assert client.delete("/credentials/io").status_code == 403
    assert client.delete("/credentials/local").status_code == 404
    assert client.patch("/credentials/missing", json={"label": "Valid"}).status_code == 404
    assert "local" in _config(home)["model_aliases"]


def test_legacy_manual_pool_rows_are_migrated_out_of_the_pool(api):
    _module, client, home = api
    from hermes_cli.auth import write_credential_pool
    write_credential_pool("bonzai", [
        {"id": "aaa111", "label": "BONZAI_API_KEY", "auth_type": "api_key", "priority": 0,
         "source": "env:BONZAI_API_KEY"},
        {"id": "bbb222", "label": "Landal", "auth_type": "api_key", "priority": 1,
         "source": "manual", "access_token": "landal-super-secret"},
        {"id": "ccc333", "label": "Default", "auth_type": "api_key", "priority": 2,
         "source": "manual", "access_token": "odd-super-secret"},
    ])

    payload = client.get("/credentials").json()

    assert payload["migrated"] == 2
    assert [row["slug"] for row in payload["credentials"]] == ["io", "client-ccc333", "landal"]
    assert [row["source"] for row in _pool_rows(home)] == ["env:BONZAI_API_KEY"]
    assert "BONZAI_LANDAL_API_KEY=landal-super-secret" in _env(home)
    assert "BONZAI_CLIENT_CCC333_API_KEY=odd-super-secret" in _env(home)
    assert "super-secret" not in json.dumps(payload)
    assert client.get("/credentials").json()["migrated"] == 0


def test_migration_keeps_an_existing_alias_and_secret(api):
    _module, client, home = api
    (home / "config.yaml").write_text(yaml.safe_dump({
        "model_aliases": {"landal": {
            "model": "claude-sonnet-5", "provider": "custom",
            "base_url": BONZAI_URL, "key_env": "BONZAI_LANDAL_API_KEY",
        }},
    }))
    (home / ".env").write_text("BONZAI_LANDAL_API_KEY=edited-by-hand\n")
    from hermes_cli.auth import write_credential_pool
    write_credential_pool("bonzai", [
        {"id": "bbb222", "label": "Landal", "auth_type": "api_key", "priority": 0,
         "source": "manual", "access_token": "stale-pool-copy"},
    ])

    client.get("/credentials")

    alias = _config(home)["model_aliases"]["landal"]
    assert alias["model"] == "claude-sonnet-5"
    assert alias["label"] == "Landal"
    assert "BONZAI_LANDAL_API_KEY=edited-by-hand" in _env(home)
    assert "stale-pool-copy" not in _env(home)
    assert _pool_rows(home) == []


def test_test_key_uses_injected_checker_without_persisting(api, monkeypatch):
    module, client, home = api
    calls = []
    monkeypatch.setattr(module, "key_checker", lambda key: calls.append(key) or {"ok": True, "status": 200})

    response = client.post("/credentials/test", json={"api_key": "candidate-super-secret"})

    assert response.json() == {"ok": True, "status": 200}
    assert calls == ["candidate-super-secret"]
    assert "candidate-super-secret" not in _env(home)


def test_test_key_reports_upstream_failure_without_leaking_key(api, monkeypatch):
    module, client, _home = api
    monkeypatch.setattr(module, "key_checker", lambda _key: {"ok": False, "status": 401, "error": "Unauthorized"})

    response = client.post("/credentials/test", json={"api_key": "bad-super-secret"})

    assert response.json() == {"ok": False, "status": 401, "error": "Unauthorized"}
    assert "bad-super-secret" not in response.text


def test_stored_keys_are_tested_server_side(api, monkeypatch):
    module, client, _home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})
    calls = []
    monkeypatch.setattr(module, "key_checker", lambda key: calls.append(key) or {"ok": True, "status": 200})

    assert client.post("/credentials/test-stored", json={"id": "landal"}).json() == {"ok": True, "status": 200}
    assert client.post("/credentials/test-stored", json={"id": "io"}).status_code == 200
    assert client.post("/credentials/test-stored", json={"id": "missing"}).status_code == 404
    assert calls == ["landal-super-secret", "env-super-secret"]


def test_activate_is_kept_for_older_desktop_companions(api):
    _module, client, _home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})

    assert client.post("/credentials/landal/activate").json() == {"slug": "landal", "label": "Landal"}
    assert client.post("/credentials/io/activate").json()["slug"] == "io"
    assert client.post("/credentials/missing/activate").status_code == 404


def test_session_key_assignments_can_be_read_and_set(api):
    _module, client, _home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-secret"})

    assert client.get("/sessions/test-chat-1").json()["slug"] == "io"
    assert client.post("/sessions/test-chat-1", json={"slug": "landal"}).json()["slug"] == "landal"
    assert client.get("/sessions").json()["sessions"] == {"test-chat-1": "landal"}

    # An accepted default selection is advisory state, just like a client.
    client.post("/sessions/test-chat-1", json={"slug": "io"})
    assert client.get("/sessions").json()["sessions"] == {"test-chat-1": "io"}


def test_session_key_store_writes_json_atomically(api):
    _module, _client, home = api
    store = home / "bonzai_session_keys.json"
    store.write_text('{"chat-1":"landal"}\n')
    _module._atomic_write_json(store, {"chat-2": "heineken"})

    assert json.loads(store.read_text()) == {"chat-2": "heineken"}
    assert list(home.glob(".bonzai_session_keys.json.*")) == []


def test_session_key_assignments_reject_invalid_values(api):
    _module, client, _home = api
    assert client.post("/sessions/../escape", json={"slug": "valid"}).status_code in (404, 405, 422)
    assert client.post("/sessions/valid", json={"slug": "../bad"}).status_code == 422
    assert client.post("/sessions/valid", json={"slug": "-bad-"}).status_code == 422
    assert client.get("/sessions/bad%20id").status_code == 422


def test_corrupt_session_store_fails_closed(api):
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-secret"})
    (home / "bonzai_session_keys.json").write_text("{not json")

    assert client.get("/sessions").json() == {"sessions": {}}
    assert client.post("/sessions/chat-1", json={"slug": "landal"}).status_code == 200
    assert client.get("/sessions").json() == {"sessions": {"chat-1": "landal"}}


def test_installer_and_key_manager_agree_on_alias_names(api):
    """Both entry points must write the same alias for a client, or a key
    added in the terminal shows up twice in Desktop."""
    module, _client, _home = api
    spec = importlib.util.spec_from_file_location("bonzai_installer_parity", REPO / "install.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)

    for label in ["Landal", "Landal NL", "_Heineken_", "Ünïcødé 2", "a -- b", "ACME/Beta"]:
        assert installer.slugify(label) == module.slugify(label), label
    assert installer.RESERVED_ALIASES == module.RESERVED_SLUGS


def test_key_manager_manifests_exist_and_reference_dashboard_api():
    plugin_manifest = yaml.safe_load((REPO / "key-manager" / "plugin.yaml").read_text())
    dashboard = json.loads((REPO / "key-manager" / "dashboard" / "manifest.json").read_text())

    assert plugin_manifest["kind"] == "backend"
    assert dashboard["api"] == "plugin_api.py"
    assert dashboard["version"] == plugin_manifest["version"]
    assert (REPO / "key-manager" / "__init__.py").exists()


def test_failed_alias_save_rolls_back_new_secret(api, monkeypatch):
    module, _client, home = api
    def fail(_cfg):
        raise OSError("config is read-only")
    monkeypatch.setattr(module, "save_config", fail)
    with pytest.raises(OSError, match="read-only"):
        module.add_credential(module.AddCredentialRequest(label="Landal", api_key="candidate-secret"))
    assert "candidate-secret" not in _env(home)
    assert "landal" not in _config(home).get("model_aliases", {})


def test_add_does_not_overwrite_an_orphaned_existing_secret(api):
    _module, client, home = api
    with (home / ".env").open("a") as handle:
        handle.write("BONZAI_LANDAL_API_KEY=preserve-orphan\n")
    response = client.post("/credentials", json={"label": "Landal", "api_key": "replacement"})
    assert response.status_code == 409
    assert "preserve-orphan" in _env(home)


def test_concurrent_adds_preserve_all_aliases(api):
    module, _client, home = api
    from concurrent.futures import ThreadPoolExecutor

    import time
    # Real config reader/writer with a short yield to expose lost updates.
    def read():
        cfg = _config(home)
        time.sleep(0.01)
        return cfg
    module.load_config = read
    def add(index):
        return module.add_credential(module.AddCredentialRequest(label=f"Client {index}", api_key=f"synthetic-{index}"))
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(add, range(8)))
    assert set(_config(home)["model_aliases"]) == {f"client-{index}" for index in range(8)}


def test_migration_keeps_distinct_keys_with_identical_labels(api):
    _module, client, home = api
    from hermes_cli.auth import write_credential_pool
    write_credential_pool("bonzai", [
        {"id": "first", "label": "Landal", "auth_type": "api_key", "source": "manual", "access_token": "first-secret"},
        {"id": "second", "label": "Landal", "auth_type": "api_key", "source": "manual", "access_token": "second-secret"},
    ])
    assert client.get("/credentials").json()["migrated"] == 2
    aliases = _config(home)["model_aliases"]
    assert set(aliases) == {"landal", "landal-second"}
    assert "first-secret" in _env(home) and "second-secret" in _env(home)


def test_key_checker_does_not_forward_key_to_redirected_host(api, monkeypatch):
    module, _client, _home = api
    import urllib.request
    import urllib.error
    from http.client import HTTPMessage
    from io import BytesIO
    captured = {}
    def build(*handlers):
        captured["handlers"] = handlers
        class Opener:
            def open(self, request, **kwargs):
                handler = next(h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
                try:
                    redirected = handler.redirect_request(request, BytesIO(), 302, "Found", HTTPMessage(), "https://example.invalid/models")
                except urllib.error.HTTPError:
                    return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda *_: None, "read": lambda *_: b"", "status": 200})()
                assert redirected is not None and not redirected.has_header("Authorization")
                return type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda *_: None, "read": lambda *_: b"", "status": 200})()
        return Opener()
    monkeypatch.setattr(module.urllib.request, "build_opener", build)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *_args, **_kwargs: pytest.fail("unguarded urlopen"))
    assert module.key_checker("synthetic-key")["ok"] is True


def test_session_binding_requires_a_configured_client_alias(api):
    _module, client, home = api
    assert client.post("/sessions/chat-1", json={"slug": "missing"}).status_code == 404
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-secret"})
    (home / ".env").write_text("BONZAI_API_KEY=env-super-secret\n")
    assert client.post("/sessions/chat-1", json={"slug": "landal"}).status_code == 409
    assert client.get("/sessions").json()["sessions"] == {}


def test_add_detects_a_silently_refused_config_write(api, monkeypatch):
    module, client, home = api
    monkeypatch.setattr(module, "save_config", lambda cfg: None)
    response = client.post("/credentials", json={"label": "Landal", "api_key": "candidate-secret"})
    assert response.status_code == 409
    assert "candidate-secret" not in _env(home)


def test_migration_does_not_remove_pool_rows_after_refused_config_write(api, monkeypatch):
    module, client, home = api
    from hermes_cli.auth import write_credential_pool
    write_credential_pool("bonzai", [
        {"id": "first", "label": "Landal", "auth_type": "api_key", "source": "manual", "access_token": "first-secret"},
    ])
    monkeypatch.setattr(module, "save_config", lambda cfg: None)
    assert client.get("/credentials").status_code == 409
    assert len(_pool_rows(home)) == 1


def test_migration_never_overwrites_a_foreign_suffixed_alias(api):
    _module, client, home = api
    foreign = {"model": "keep", "provider": "custom", "base_url": "http://localhost:1234"}
    (home / "config.yaml").write_text(yaml.safe_dump({"model_aliases": {"landal": foreign, "landal-first": foreign}}))
    from hermes_cli.auth import write_credential_pool
    write_credential_pool("bonzai", [{"id": "first", "label": "Landal", "auth_type": "api_key", "source": "manual", "access_token": "first-secret"}])
    assert client.get("/credentials").status_code == 200
    aliases = _config(home)["model_aliases"]
    assert aliases["landal"] == foreign
    assert aliases["landal-first"] == foreign
    assert len(aliases) == 3


def test_migration_retry_reuses_stable_aliases_after_pool_save_failure(api, monkeypatch):
    module, _client, home = api
    from hermes_cli.auth import write_credential_pool
    write_credential_pool("bonzai", [
        {"id": "first", "label": "Landal", "auth_type": "api_key", "source": "manual", "access_token": "first-secret"},
        {"id": "second", "label": "Landal", "auth_type": "api_key", "source": "manual", "access_token": "second-secret"},
    ])
    original = module._save_auth_store
    monkeypatch.setattr(module, "_save_auth_store", lambda store: (_ for _ in ()).throw(OSError("pool write failed")))
    with pytest.raises(OSError, match="pool write failed"):
        module.migrate_legacy_pool_entries()
    aliases_before = _config(home)["model_aliases"]
    monkeypatch.setattr(module, "_save_auth_store", original)
    module.migrate_legacy_pool_entries()
    assert _config(home)["model_aliases"] == aliases_before
    assert len(aliases_before) == 2
