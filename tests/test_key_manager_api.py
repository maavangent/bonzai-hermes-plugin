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
        "model": "gemini-3.7-flash",
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


def test_remove_deletes_alias_secret_and_session_bindings(api):
    _module, client, home = api
    client.post("/credentials", json={"label": "Landal", "api_key": "landal-super-secret"})
    client.post("/sessions/chat-1", json={"slug": "landal"})

    assert client.delete("/credentials/landal").status_code == 204

    assert "landal" not in _config(home).get("model_aliases", {})
    assert "landal-super-secret" not in _env(home)
    assert client.get("/sessions/chat-1").json()["slug"] == "io"


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
    assert not (home / ".env").exists()


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

    assert client.get("/sessions/test-chat-1").json()["slug"] == "io"
    assert client.post("/sessions/test-chat-1", json={"slug": "landal"}).json()["slug"] == "landal"
    assert client.get("/sessions").json()["sessions"] == {"test-chat-1": "landal"}

    # Returning to the default drops the binding instead of storing "io" forever.
    client.post("/sessions/test-chat-1", json={"slug": "io"})
    assert client.get("/sessions").json()["sessions"] == {}


def test_session_key_assignments_reject_invalid_values(api):
    _module, client, _home = api
    assert client.post("/sessions/../escape", json={"slug": "valid"}).status_code in (404, 405, 422)
    assert client.post("/sessions/valid", json={"slug": "../bad"}).status_code == 422
    assert client.post("/sessions/valid", json={"slug": "-bad-"}).status_code == 422
    assert client.get("/sessions/bad%20id").status_code == 422


def test_corrupt_session_store_fails_closed(api):
    _module, client, home = api
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
