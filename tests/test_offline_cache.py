from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


def load_plugin():
    providers = types.ModuleType("providers")
    providers.register_provider = lambda _profile: None  # type: ignore[attr-defined]
    base = types.ModuleType("providers.base")

    class ProviderProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    base.ProviderProfile = ProviderProfile  # type: ignore[attr-defined]
    sys.modules["providers"] = providers
    sys.modules["providers.base"] = base

    path = Path(__file__).parents[1] / "bonzai" / "__init__.py"
    spec = importlib.util.spec_from_file_location("bonzai_offline_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    module = load_plugin()
    module._CACHE["models"] = None
    module._CACHE["ts"] = 0
    return module


def test_profile_ships_no_fallback_models_so_the_live_order_wins(plugin):
    # Hermes merges ProviderProfile.fallback_models AHEAD of the live list
    # (hermes_cli/models.py::provider_model_ids). A non-empty tuple therefore
    # pins a stale hand-written order to the top of the picker and buries newly
    # released flagships. Ordering must come from fetch_models alone.
    assert plugin.bonzai.fallback_models == ()


def test_a_successful_fetch_is_persisted_for_offline_use(plugin, tmp_path):
    plugin._store_offline_models(["claude-opus-5", "gpt-5.6-sol"])

    saved = json.loads((tmp_path / "bonzai_models_cache.json").read_text())

    assert saved["models"] == ["claude-opus-5", "gpt-5.6-sol"]


def test_fetch_falls_back_to_the_last_good_list_when_the_api_is_unreachable(plugin):
    plugin._store_offline_models(["claude-opus-5", "claude-opus-4-8"])

    def boom(*_args, **_kwargs):
        raise OSError("network down")

    plugin.urllib.request.urlopen = boom

    assert plugin.bonzai.fetch_models(api_key="dummy") == [
        "claude-opus-5",
        "claude-opus-4-8",
    ]


def test_fetch_returns_none_when_offline_with_no_cached_list(plugin):
    def boom(*_args, **_kwargs):
        raise OSError("network down")

    plugin.urllib.request.urlopen = boom

    assert plugin.bonzai.fetch_models(api_key="dummy") is None


def test_a_corrupt_offline_cache_is_ignored_rather_than_raising(plugin, tmp_path):
    (tmp_path / "bonzai_models_cache.json").write_text("{not json")

    assert plugin._load_offline_models() is None
