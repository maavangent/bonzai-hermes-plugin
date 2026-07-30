from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

INSTALLER = Path(__file__).parents[1] / "install.py"

PROVIDERS_STUB = '''\
"""Fake hermes_cli/providers.py for installer tests."""

HERMES_OVERLAYS: Dict[str, HermesOverlay] = {
    "openai": HermesOverlay(
        transport="openai_chat",
        auth_type="api_key",
    ),
}
'''


def load_installer(home: Path):
    """Import install.py with HERMES_HOME pointed at a temp dir."""
    sys.modules.pop("bonzai_installer_test", None)
    spec = importlib.util.spec_from_file_location("bonzai_installer_test", INSTALLER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # install.py resolves paths at import time; retarget them at the temp home.
    module.HERMES_HOME = home
    module.PLUGIN_DIR = home / "plugins" / "model-providers" / "bonzai"
    module.PROVIDERS_FILE = home / "hermes-agent" / "hermes_cli" / "providers.py"
    module.CACHE_FILE = home / "provider_models_cache.json"
    return module


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    providers = tmp_path / "hermes-agent" / "hermes_cli" / "providers.py"
    providers.parent.mkdir(parents=True)
    providers.write_text(PROVIDERS_STUB)
    return tmp_path, load_installer(tmp_path), providers


def test_overlay_is_injected_into_the_overlays_dict(env):
    _home, installer, providers = env

    installer.add_overlay()

    assert '"bonzai": HermesOverlay(' in providers.read_text()


def test_injecting_twice_does_not_duplicate_the_entry(env):
    _home, installer, providers = env

    installer.add_overlay()
    installer.add_overlay()

    assert providers.read_text().count('"bonzai": HermesOverlay(') == 1


def test_the_injected_file_is_still_valid_python(env):
    _home, installer, providers = env

    installer.add_overlay()

    # Compiles => no stray comma/indent damage in the user's Hermes source.
    compile(providers.read_text(), str(providers), "exec")


def test_uninstall_restores_the_file_byte_for_byte(env):
    _home, installer, providers = env
    before = providers.read_text()

    installer.add_overlay()
    installer.remove_overlay()

    assert providers.read_text() == before


def test_a_hermes_update_that_dropped_the_overlay_is_detected(env):
    _home, installer, providers = env

    assert installer.overlay_missing() is True

    installer.add_overlay()

    assert installer.overlay_missing() is False


def test_overlay_is_reported_missing_when_a_hermes_update_rewrote_providers_py(env):
    _home, installer, providers = env
    installer.add_overlay()

    # Simulate `hermes update` replacing the file with a fresh upstream copy.
    providers.write_text(PROVIDERS_STUB)

    assert installer.overlay_missing() is True
