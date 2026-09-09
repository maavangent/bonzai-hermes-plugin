from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


REPO = Path(__file__).resolve().parents[1]
HERMES_SOURCE = Path.home() / ".hermes" / "hermes-agent"
API_PATH = REPO / "key-manager" / "dashboard" / "plugin_api.py"


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("BONZAI_API_KEY", "env-super-secret")
    sys.path.insert(0, str(HERMES_SOURCE))
    sys.path.insert(0, str(REPO))
    saved_modules = {
        name: sys.modules.get(name)
        for name in ("providers", "providers.base", "bonzai")
    }
    for name in saved_modules:
        sys.modules.pop(name, None)
    try:
        import bonzai  # noqa: F401 - registers the provider for env seeding

        spec = importlib.util.spec_from_file_location("bonzai_key_manager_api", API_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        app = FastAPI()
        app.include_router(module.router)
        yield module, TestClient(app), tmp_path
    finally:
        sys.path.remove(str(REPO))
        sys.path.remove(str(HERMES_SOURCE))
        sys.modules.pop("bonzai_key_manager_api", None)
        for name in saved_modules:
            sys.modules.pop(name, None)
        for name, module in saved_modules.items():
            if module is not None:
                sys.modules[name] = module


def test_list_credentials_returns_secret_free_metadata_and_strategy(api):
    _module, client, _home = api

    response = client.get("/credentials")

    assert response.status_code == 200
    payload = response.json()
    assert payload["strategy"] == "fill_first"
    assert len(payload["credentials"]) == 1
    credential = payload["credentials"][0]
    assert set(credential) == {
        "id", "label", "source", "auth_type", "status", "cooldown_until",
        "removable", "renameable",
    }
    assert credential["id"]
    assert credential | {"id": "ignored"} == {
        "id": "ignored",
        "label": "BONZAI_API_KEY",
        "source": "env:BONZAI_API_KEY",
        "auth_type": "api_key",
        "status": "ok",
        "cooldown_until": None,
        "removable": False,
        "renameable": False,
    }
    serialized = json.dumps(payload)
    assert "env-super-secret" not in serialized
    assert "access_token" not in serialized
    assert "runtime_api_key" not in serialized


def test_add_manual_credential_persists_but_response_hides_key(api):
    _module, client, home = api

    response = client.post("/credentials", json={"label": "Work", "api_key": "manual-super-secret"})

    assert response.status_code == 201
    credential = response.json()["credential"]
    assert credential["label"] == "Work"
    assert credential["source"] == "manual"
    assert credential["removable"] is True
    assert "manual-super-secret" not in json.dumps(response.json())
    stored = json.loads((home / "auth.json").read_text())
    manual = next(row for row in stored["credential_pool"]["bonzai"] if row["source"] == "manual")
    assert manual["access_token"] == "manual-super-secret"


@pytest.mark.parametrize("body", [
    {"label": "", "api_key": "valid"},
    {"label": "Work", "api_key": ""},
    {"label": "Work", "api_key": "  "},
])
def test_add_rejects_invalid_input(api, body):
    _module, client, _home = api
    assert client.post("/credentials", json=body).status_code == 422


def test_test_key_uses_injected_checker_without_persisting(api, monkeypatch):
    module, client, home = api
    calls = []
    monkeypatch.setattr(module, "key_checker", lambda key: calls.append(key) or {"ok": True, "status": 200})

    response = client.post("/credentials/test", json={"api_key": "candidate-super-secret"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": 200}
    assert calls == ["candidate-super-secret"]
    assert "candidate-super-secret" not in json.dumps(response.json())
    assert not (home / "auth.json").exists()


def test_test_key_reports_upstream_failure_without_leaking_key(api, monkeypatch):
    module, client, _home = api
    monkeypatch.setattr(module, "key_checker", lambda _key: {"ok": False, "status": 401, "error": "Unauthorized"})

    response = client.post("/credentials/test", json={"api_key": "bad-super-secret"})

    assert response.status_code == 200
    assert response.json() == {"ok": False, "status": 401, "error": "Unauthorized"}
    assert "bad-super-secret" not in response.text


def test_stored_key_is_tested_server_side_without_returning_secret(api, monkeypatch):
    module, client, _home = api
    added = client.post(
        "/credentials", json={"label": "Stored", "api_key": "stored-super-secret"}
    ).json()["credential"]
    calls = []
    monkeypatch.setattr(
        module,
        "key_checker",
        lambda key: calls.append(key) or {"ok": True, "status": 200},
    )

    response = client.post("/credentials/test-stored", json={"id": added["id"]})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": 200}
    assert calls == ["stored-super-secret"]
    assert "stored-super-secret" not in response.text


def test_rename_and_remove_apply_only_to_manual_credentials(api):
    _module, client, _home = api
    entries = client.get("/credentials").json()["credentials"]
    env_id = entries[0]["id"]
    manual = client.post(
        "/credentials", json={"label": "Work", "api_key": "manual-super-secret"}
    ).json()["credential"]

    renamed = client.patch(
        f"/credentials/{manual['id']}", json={"label": "Renamed"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["credential"]["label"] == "Renamed"
    assert client.delete(f"/credentials/{manual['id']}").status_code == 204
    assert [row["id"] for row in client.get("/credentials").json()["credentials"]] == [env_id]

    assert client.patch(f"/credentials/{env_id}", json={"label": "Nope"}).status_code == 403
    assert client.delete(f"/credentials/{env_id}").status_code == 403


def test_rename_remove_reject_invalid_or_missing_targets(api):
    _module, client, _home = api
    assert client.patch("/credentials/missing", json={"label": "Valid"}).status_code == 404
    assert client.delete("/credentials/missing").status_code == 404
    manual = client.post(
        "/credentials", json={"label": "Work", "api_key": "manual-super-secret"}
    ).json()["credential"]
    assert client.patch(f"/credentials/{manual['id']}", json={"label": "  "}).status_code == 422


def test_reset_cooldowns_clears_failure_metadata(api):
    module, client, home = api
    manual = client.post(
        "/credentials", json={"label": "Work", "api_key": "manual-super-secret"}
    ).json()["credential"]
    pool = module.load_pool("bonzai")
    entry = next(row for row in pool.entries() if row.id == manual["id"])
    pool._mark_exhausted(entry, 429)

    response = client.post("/credentials/reset")

    assert response.status_code == 200
    assert response.json() == {"reset": 1}
    stored = json.loads((home / "auth.json").read_text())
    row = next(item for item in stored["credential_pool"]["bonzai"] if item["id"] == manual["id"])
    assert row.get("last_status") is None
    assert row.get("last_error_code") is None


@pytest.mark.parametrize("strategy", ["fill_first", "round_robin", "least_used", "random"])
def test_strategy_can_be_read_and_written(api, strategy):
    _module, client, home = api

    response = client.put("/strategy", json={"strategy": strategy})

    assert response.status_code == 200
    assert response.json() == {"strategy": strategy}
    assert client.get("/strategy").json() == {"strategy": strategy}
    assert strategy in (home / "config.yaml").read_text()


def test_strategy_rejects_unknown_value(api):
    _module, client, _home = api
    assert client.put("/strategy", json={"strategy": "invented"}).status_code == 422


def test_key_manager_manifests_exist_and_reference_dashboard_api():
    plugin_manifest = (REPO / "key-manager" / "plugin.yaml").read_text()
    dashboard = json.loads((REPO / "key-manager" / "dashboard" / "manifest.json").read_text())

    assert "manifest_version: 2" in plugin_manifest
    assert dashboard["api"] == "plugin_api.py"
    assert (REPO / "key-manager" / "__init__.py").exists()
