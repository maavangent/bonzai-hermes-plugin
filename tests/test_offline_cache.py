from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest


from provider_helper import load_plugin


@pytest.fixture()
def plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    module = load_plugin()
    module._CACHE.clear()
    return module


def test_plugin_loader_restores_provider_modules():
    before = {name: sys.modules.get(name) for name in ("providers", "providers.base")}
    load_plugin()
    assert {name: sys.modules.get(name) for name in before} == before


def test_scoped_environment_read_propagates_secret_scope_failures(plugin, monkeypatch):
    """A missing multiplex secret must never fall back to the process environment."""
    agent = types.ModuleType("agent")
    agent.__path__ = []
    secret_scope = types.ModuleType("agent.secret_scope")
    secret_scope.__package__ = "agent"

    def fail_closed(_name, _default=""):
        raise RuntimeError("profile scope is missing")

    secret_scope.get_secret = fail_closed
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.secret_scope", secret_scope)
    monkeypatch.setattr(os, "getenv", lambda name, default=None: "launch-profile-key" if name == "BONZAI_API_KEY" else default)
    with pytest.raises(RuntimeError, match="profile scope is missing"):
        plugin._scoped_env("BONZAI_API_KEY")


def test_scoped_environment_read_falls_back_only_when_hermes_scope_module_is_unavailable(plugin, monkeypatch):
    agent = types.ModuleType("agent")
    agent.__path__ = []
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.delitem(sys.modules, "agent.secret_scope", raising=False)
    monkeypatch.setattr(
        os,
        "getenv",
        lambda name, default=None: "development-key" if name == "BONZAI_API_KEY" else default,
    )

    assert plugin._scoped_env("BONZAI_API_KEY") == "development-key"


def test_cache_partition_uses_active_hermes_profile_home(plugin, monkeypatch, tmp_path):
    """Two profile homes with one key must not alias their provider cache."""
    hermes_constants = types.ModuleType("hermes_constants")
    current_home = {"value": str(tmp_path / "profile-a")}
    hermes_constants.get_hermes_home = lambda: current_home["value"]
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)
    key_a = plugin._cache_key("same-key")
    current_home["value"] = str(tmp_path / "profile-b")
    key_b = plugin._cache_key("same-key")

    assert key_a != key_b


def test_in_process_cache_is_scoped_per_key(plugin, monkeypatch):
    """A catalog fetched with one key must not be served to another key."""
    calls = []

    class Response:
        def __init__(self, model):
            self.body = json.dumps({"data": [{"id": model, "mode": "chat"}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return self.body

    def urlopen(request, **_kwargs):
        key = request.get_header("Authorization")
        calls.append(key)
        return Response("claude-opus-5" if key.endswith("key-a") else "gpt-5.6")

    monkeypatch.setattr(plugin, "_open_catalog", urlopen)

    assert plugin.bonzai.fetch_models(api_key="key-a") == ["claude-opus-5"]
    assert plugin.bonzai.fetch_models(api_key="key-b") == ["gpt-5.6"]
    assert plugin.bonzai.fetch_models(api_key="key-a") == ["claude-opus-5"]
    assert len(calls) == 2
    assert all("key-" not in key for key in plugin._CACHE)


def test_in_process_cache_restores_its_credential_metadata(plugin, monkeypatch):
    class Response:
        def __init__(self, limit): self.limit = limit
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return json.dumps({"data": [{"id": "gpt-6.1-sol", "mode": "chat", "max_output_tokens": self.limit}]}).encode()
    monkeypatch.setattr(plugin, "_open_catalog", lambda request, **k: Response(4096 if request.get_header("Authorization").endswith("a") else 8192))
    plugin.bonzai.fetch_models(api_key="synthetic-a")
    plugin.bonzai.fetch_models(api_key="synthetic-b")
    assert plugin._catalog_capabilities(plugin._CACHE[plugin._cache_key("synthetic-b")]["items"])["gpt-6.1-sol"]["max_output_tokens"] == 8192
    plugin.bonzai.fetch_models(api_key="synthetic-a")
    assert plugin._catalog_capabilities(plugin._CACHE[plugin._cache_key("synthetic-a")]["items"])["gpt-6.1-sol"]["max_output_tokens"] == 4096
    assert plugin.bonzai.get_max_tokens("gpt-6.1-sol") == 32768


def test_credential_catalog_limits_do_not_mutate_provider_wide_metadata(plugin, monkeypatch):
    baseline = dict(plugin.bonzai.model_capabilities)
    class Response:
        def __init__(self, limited): self.limited = limited
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self):
            item: dict = {"id": "gpt-6.1-sol", "mode": "chat"}
            if self.limited:
                item.update(max_input_tokens=200000, max_output_tokens=4096)
            return json.dumps({"data": [item]}).encode()
    monkeypatch.setattr(plugin, "_open_catalog", lambda request, **k: Response(request.get_header("Authorization").endswith("a")))
    plugin.bonzai.fetch_models(api_key="synthetic-a")
    plugin.bonzai.fetch_models(api_key="synthetic-b")
    assert plugin.bonzai.model_capabilities == baseline
    assert plugin.bonzai.get_max_tokens("gpt-6.1-sol") == 32768
    plugin.bonzai.fetch_models(api_key="synthetic-a")  # memory-hit path is equally isolated
    assert plugin.bonzai.model_capabilities == baseline
    assert plugin.bonzai.get_max_tokens("gpt-6.1-sol") == 32768


def test_profile_switch_cannot_inherit_catalog_metadata(plugin, monkeypatch, tmp_path):
    constants = types.ModuleType("hermes_constants")
    current_home = {"value": tmp_path / "profile-a"}
    constants.get_hermes_home = lambda: current_home["value"]
    monkeypatch.setitem(sys.modules, "hermes_constants", constants)
    baseline = dict(plugin.bonzai.model_capabilities)
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self):
            return b'{"data": [{"id": "gpt-6.1-sol", "mode": "chat", "max_output_tokens": 4096}]}'
    monkeypatch.setattr(plugin, "_open_catalog", lambda *a, **k: Response())
    plugin.bonzai.fetch_models(api_key="synthetic")
    current_home["value"] = tmp_path / "profile-b"
    # No discovery, disk read, or ambient key lookup is needed in the hot path.
    def forbidden(*a, **k): raise AssertionError("hot path must not discover credentials or read disk")
    monkeypatch.setattr(plugin, "_scoped_env", forbidden)
    monkeypatch.setattr(plugin, "_load_offline_models", forbidden)
    assert plugin.bonzai.get_max_tokens("gpt-6.1-sol") == 32768
    assert plugin.bonzai.model_capabilities == baseline
    current_home["value"] = tmp_path / "profile-a"
    assert plugin.bonzai.get_max_tokens("gpt-6.1-sol") == 32768
    assert plugin.bonzai.model_capabilities == baseline


def test_catalog_refresh_invalidates_plugin_memory_cache(plugin):
    plugin._CACHE["a"] = {"models": ["gpt-5.6"], "ts": plugin.time.time()}
    plugin.bonzai.invalidate_catalog_cache()
    assert plugin._CACHE == {}


def test_catalog_fetch_uses_hermes_credential_safe_opener(plugin, monkeypatch):
    safe = types.ModuleType("hermes_cli.urllib_security")
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b'{"data": [{"id": "gpt-6.1-sol"}]}'
    def open_safe(request, **kwargs):
        calls.append((request, kwargs))
        return Response()
    setattr(safe, "open_credentialed_url", open_safe)
    monkeypatch.setitem(sys.modules, "hermes_cli.urllib_security", safe)
    def unsafe(*a, **k): raise AssertionError("plain urlopen must not receive credentials")
    monkeypatch.setattr(plugin.urllib.request, "urlopen", unsafe)
    assert plugin.bonzai.fetch_models(api_key="synthetic", base_url="https://other.invalid") == ["gpt-6.1-sol"]
    assert len(calls) == 1
    assert calls[0][0].full_url == "https://api-v2.bonzai.iodigital.com/v1/models"
    assert calls[0][1]["ssl_context"].verify_mode == plugin.ssl.CERT_REQUIRED


def test_older_hermes_rejects_cross_origin_redirects(plugin, monkeypatch):
    import urllib.error
    import urllib.request
    legacy = types.ModuleType("hermes_cli")
    legacy.__path__ = []
    monkeypatch.setitem(sys.modules, "hermes_cli", legacy)
    monkeypatch.delitem(sys.modules, "hermes_cli.urllib_security", raising=False)
    captured = []
    class Opener:
        def open(self, request, **kwargs):
            captured.append(request)
            redirect = next(h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
            same = redirect.redirect_request(request, None, 302, "redirect", {}, "https://api-v2.bonzai.iodigital.com:443/next")
            assert same.get_header("Authorization") == "Bearer synthetic"
            for url in ("https://foreign.invalid/models", "http://api-v2.bonzai.iodigital.com/models", "https://api-v2.bonzai.iodigital.com:444/models"):
                with pytest.raises(urllib.error.HTTPError, match="cross-origin"):
                    redirect.redirect_request(request, None, 302, "redirect", {}, url)
            raise OSError("synthetic end")
    handlers = []
    def build_opener(*args):
        handlers.extend(args)
        return Opener()
    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    assert plugin.bonzai.fetch_models(api_key="synthetic") is None
    assert len(captured) == 1


def test_profile_ships_no_fallback_models_so_the_live_order_wins(plugin):
    # Hermes merges ProviderProfile.fallback_models AHEAD of the live list
    # (hermes_cli/models.py::provider_model_ids). A non-empty tuple therefore
    # pins a stale hand-written order to the top of the picker and buries newly
    # released flagships. Ordering must come from fetch_models alone.
    assert plugin.bonzai.fallback_models == ()


def test_offline_cache_is_bound_to_the_fetch_credential(plugin):
    plugin._store_offline_models(["claude-opus-5"], api_key="synthetic-a")
    assert plugin._load_offline_models(api_key="synthetic-b") is None
    assert plugin._load_offline_models(api_key="synthetic-a") == ["claude-opus-5"]


def test_offline_cache_replace_is_atomic_and_owner_only(plugin, tmp_path, monkeypatch):
    plugin._store_offline_models(["gpt-5.6"], api_key="dummy")
    path = tmp_path / "bonzai_models_cache.json"
    original = path.read_bytes()
    calls = []

    def interrupted_replace(source, target):
        calls.append((source, target))
        assert Path(source).read_text() != original.decode()
        assert Path(source).stat().st_mode & 0o777 == 0o600
        assert path.read_bytes() == original
        raise OSError("interrupted")

    monkeypatch.setattr(plugin.os, "replace", interrupted_replace)
    plugin._store_offline_models(["gpt-6.1-sol"], api_key="dummy")
    assert len(calls) == 1
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_offline_start_restores_catalog_metadata(plugin, monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self):
            return json.dumps({"data": [{"id": "gpt-6.1-sol", "mode": "chat", "max_input_tokens": 200000, "max_output_tokens": 4096}]}).encode()

    monkeypatch.setattr(plugin, "_open_catalog", lambda *a, **k: Response())
    assert plugin.bonzai.fetch_models(api_key="dummy") == ["gpt-6.1-sol"]
    plugin._CACHE.clear()
    def offline(*a, **k): raise OSError("offline")
    monkeypatch.setattr(plugin, "_open_catalog", offline)
    assert plugin.bonzai.fetch_models(api_key="dummy") == ["gpt-6.1-sol"]
    saved = json.loads(plugin._offline_cache_path().read_text())
    assert plugin._catalog_capabilities(saved["items"])["gpt-6.1-sol"]["context_window"] == 200000
    assert "gpt-6.1-sol" not in plugin.bonzai.model_capabilities
    assert plugin.bonzai.get_max_tokens("gpt-6.1-sol") == 32768


def test_cache_persists_only_validated_metadata(plugin, tmp_path):
    plugin._store_offline_models(["gpt-6.1-sol"], api_key="synthetic", items=[
        {"id": "gpt-6.1-sol", "mode": "chat", "max_input_tokens": 200000, "max_output_tokens": 4096, "internal": "must-not-persist"},
        {"id": "bad id", "mode": "chat", "max_output_tokens": True},
    ])
    saved = (tmp_path / "bonzai_models_cache.json").read_text()
    assert "must-not-persist" not in saved
    assert "synthetic" not in saved
    assert "bad id" not in saved


def test_invalid_live_catalog_does_not_replace_last_good_cache(plugin, monkeypatch):
    plugin._store_offline_models(["gpt-6.1-sol"], api_key="dummy")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b'{"data": [{"id": null}, {"id": "gpt-6.1-sol\\n"}]}'
    monkeypatch.setattr(plugin, "_open_catalog", lambda *a, **k: Response())
    assert plugin.bonzai.fetch_models(api_key="dummy") == ["gpt-6.1-sol"]
    assert plugin._load_offline_models(api_key="dummy") == ["gpt-6.1-sol"]


def test_a_successful_fetch_is_persisted_for_offline_use(plugin, tmp_path):
    plugin._store_offline_models(["claude-opus-5", "gpt-5.6-sol"], api_key="dummy")

    saved = json.loads((tmp_path / "bonzai_models_cache.json").read_text())

    assert saved["models"] == ["claude-opus-5", "gpt-5.6-sol"]


def test_fetch_falls_back_to_the_last_good_list_when_the_api_is_unreachable(plugin, monkeypatch):
    plugin._store_offline_models(["claude-opus-5", "claude-opus-4-8"], api_key="dummy")

    def boom(*_args, **_kwargs):
        raise OSError("network down")

    monkeypatch.setattr(plugin, "_open_catalog", boom)

    assert plugin.bonzai.fetch_models(api_key="dummy") == [
        "claude-opus-5",
        "claude-opus-4-8",
    ]


def test_fetch_returns_none_when_offline_with_no_cached_list(plugin, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("network down")

    monkeypatch.setattr(plugin, "_open_catalog", boom)

    assert plugin.bonzai.fetch_models(api_key="dummy") is None


def test_a_corrupt_offline_cache_is_ignored_rather_than_raising(plugin, tmp_path):
    (tmp_path / "bonzai_models_cache.json").write_text("{not json")

    assert plugin._load_offline_models(api_key="dummy") is None
