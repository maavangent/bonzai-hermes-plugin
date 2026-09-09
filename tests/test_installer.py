from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

INSTALLER = Path(__file__).parents[1] / "install.py"
MANIFEST = Path(__file__).parents[1] / "bonzai" / "plugin.yaml"

PROVIDERS_STUB = '''\
"""Fake hermes_cli/providers.py for installer tests."""

HERMES_OVERLAYS: Dict[str, HermesOverlay] = {
    "openai": HermesOverlay(
        transport="openai_chat",
        auth_type="api_key",
    ),
}
'''


def test_provider_manifest_declares_v2_metadata():
    manifest = MANIFEST.read_text()

    assert "manifest_version: 2" in manifest
    assert "api_version: 1" in manifest
    assert "license: MIT" in manifest
    assert "homepage: https://github.com/maavangent/bonzai-hermes-plugin" in manifest
    assert "tags: [model-provider, bonzai, iodigital]" in manifest


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
    module.KEY_MANAGER_DIR = home / "plugins" / "bonzai-key-manager"
    module.DESKTOP_PLUGIN_FILE = home / "desktop-plugins" / "bonzai-key-manager" / "plugin.js"
    module.PROVIDERS_FILE = home / "hermes-agent" / "hermes_cli" / "providers.py"
    module.CACHE_FILE = home / "provider_models_cache.json"
    module.CONFIG_FILE = home / "config.yaml"
    return module


def test_named_profile_resolves_shared_hermes_source_root(tmp_path):
    root = tmp_path / ".hermes"
    profile_home = root / "profiles" / "work"
    installer = load_installer(profile_home)

    assert installer.resolve_hermes_root(profile_home) == root


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    providers = tmp_path / "hermes-agent" / "hermes_cli" / "providers.py"
    providers.parent.mkdir(parents=True)
    providers.write_text(PROVIDERS_STUB)
    return tmp_path, load_installer(tmp_path), providers


def test_missing_providers_file_makes_overlay_installation_fatal(tmp_path):
    installer = load_installer(tmp_path)

    with pytest.raises(RuntimeError, match="providers.py not found"):
        installer.add_overlay()


def test_incompatible_overlays_dict_makes_overlay_installation_fatal(tmp_path):
    installer = load_installer(tmp_path)
    providers = installer.PROVIDERS_FILE
    providers.parent.mkdir(parents=True)
    incompatible = "HERMES_OVERLAYS = dict(openai=HermesOverlay())\n"
    providers.write_text(incompatible)

    with pytest.raises(RuntimeError, match="Could not locate HERMES_OVERLAYS dict"):
        installer.add_overlay()

    assert providers.read_text() == incompatible


def test_install_preflights_overlay_before_replacing_existing_files(tmp_path):
    installer = load_installer(tmp_path)
    providers = installer.PROVIDERS_FILE
    providers.parent.mkdir(parents=True)
    providers.write_text("HERMES_OVERLAYS = dict(openai=HermesOverlay())\n")
    installer.PLUGIN_DIR.mkdir(parents=True)
    marker = installer.PLUGIN_DIR / "existing.txt"
    marker.write_text("keep me")

    with pytest.raises(RuntimeError, match="Could not locate HERMES_OVERLAYS dict"):
        installer.do_install()

    assert marker.read_text() == "keep me"
    assert not installer.KEY_MANAGER_DIR.exists()
    assert not installer.DESKTOP_PLUGIN_FILE.exists()


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


def test_install_deploys_and_enables_key_manager_without_changing_other_plugins(env):
    home, installer, _providers = env
    config = home / "config.yaml"
    config.write_text(yaml.safe_dump({
        "plugins": {
            "enabled": ["keep-enabled"],
            "disabled": ["bonzai-key-manager", "keep-disabled"],
        }
    }))

    installer.do_install()

    assert (installer.KEY_MANAGER_DIR / "plugin.yaml").is_file()
    assert installer.DESKTOP_PLUGIN_FILE.read_bytes() == (
        INSTALLER.parent / "key-manager" / "desktop" / "plugin.js"
    ).read_bytes()
    installed_config = yaml.safe_load(config.read_text())
    assert installed_config["plugins"]["enabled"] == ["bonzai-key-manager", "keep-enabled"]
    assert installed_config["plugins"]["disabled"] == ["keep-disabled"]


def test_named_profile_keeps_both_key_manager_installations_profile_scoped(tmp_path):
    root = tmp_path / ".hermes"
    profile_home = root / "profiles" / "work"
    installer = load_installer(profile_home)
    installer.PROVIDERS_FILE.parent.mkdir(parents=True)
    installer.PROVIDERS_FILE.write_text(PROVIDERS_STUB)

    installer.do_install()

    assert installer.KEY_MANAGER_DIR == profile_home / "plugins" / "bonzai-key-manager"
    assert installer.DESKTOP_PLUGIN_FILE == profile_home / "desktop-plugins" / "bonzai-key-manager" / "plugin.js"
    assert installer.DESKTOP_PLUGIN_FILE.is_file()
    assert not (root / "desktop-plugins" / "bonzai-key-manager" / "plugin.js").exists()


def test_uninstall_removes_both_key_manager_installations_and_only_its_enabled_key(env):
    home, installer, _providers = env
    config = home / "config.yaml"
    config.write_text(yaml.safe_dump({
        "plugins": {
            "enabled": ["bonzai-key-manager", "keep-enabled"],
            "disabled": ["keep-disabled"],
        }
    }))
    installer.KEY_MANAGER_DIR.mkdir(parents=True)
    installer.DESKTOP_PLUGIN_FILE.parent.mkdir(parents=True)
    installer.DESKTOP_PLUGIN_FILE.write_text("installed")

    installer.do_uninstall()

    assert not installer.KEY_MANAGER_DIR.exists()
    assert not installer.DESKTOP_PLUGIN_FILE.parent.exists()
    installed_config = yaml.safe_load(config.read_text())
    assert installed_config["plugins"]["enabled"] == ["keep-enabled"]
    assert installed_config["plugins"]["disabled"] == ["keep-disabled"]


def test_check_requires_backend_desktop_file_and_enabled_state(env):
    home, installer, _providers = env
    installer.PLUGIN_DIR.mkdir(parents=True)
    installer.add_overlay()
    installer.KEY_MANAGER_DIR.mkdir(parents=True)
    installer.DESKTOP_PLUGIN_FILE.parent.mkdir(parents=True)
    installer.DESKTOP_PLUGIN_FILE.write_text("installed")
    (home / "config.yaml").write_text(yaml.safe_dump({
        "plugins": {"enabled": ["bonzai-key-manager"]}
    }))

    assert installer.do_check() == 0

    installer.DESKTOP_PLUGIN_FILE.unlink()
    assert installer.do_check() == 1


def test_check_rejects_key_manager_when_explicitly_disabled(env):
    home, installer, _providers = env
    installer.PLUGIN_DIR.mkdir(parents=True)
    installer.add_overlay()
    installer.KEY_MANAGER_DIR.mkdir(parents=True)
    installer.DESKTOP_PLUGIN_FILE.parent.mkdir(parents=True)
    installer.DESKTOP_PLUGIN_FILE.write_text("installed")
    (home / "config.yaml").write_text(yaml.safe_dump({
        "plugins": {
            "enabled": ["bonzai-key-manager"],
            "disabled": ["bonzai-key-manager"],
        }
    }))

    assert installer.do_check() == 1


def test_update_stops_when_git_pull_fails(env, tmp_path, monkeypatch):
    _home, installer, _providers = env
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    monkeypatch.setattr(installer, "SCRIPT_DIR", checkout)
    installed = False

    def fail_pull(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    def record_install():
        nonlocal installed
        installed = True

    monkeypatch.setattr(installer.subprocess, "run", fail_pull)
    monkeypatch.setattr(installer, "do_install", record_install)

    with pytest.raises(RuntimeError, match="git pull failed"):
        installer.do_update()

    assert installed is False


@pytest.mark.parametrize(
    ("script_name", "installer_args"),
    [
        ("install.sh", '"$@"'),
        ("update.sh", '--update "$@"'),
        ("uninstall.sh", '--uninstall "$@"'),
    ],
)
def test_legacy_shell_scripts_are_thin_python_wrappers(script_name, installer_args):
    script = (INSTALLER.parent / script_name).read_text()

    assert f'exec "${{PYTHON:-python3}}" "$SCRIPT_DIR/install.py" {installer_args}' in script
    assert len(script.splitlines()) <= 6


def test_check_fails_when_shared_hermes_source_is_missing(tmp_path):
    installer = load_installer(tmp_path)
    installer.PLUGIN_DIR.mkdir(parents=True)
    installer.KEY_MANAGER_DIR.mkdir(parents=True)
    installer.DESKTOP_PLUGIN_FILE.parent.mkdir(parents=True)
    installer.DESKTOP_PLUGIN_FILE.write_text("installed")
    installer.set_key_manager_enabled(True)

    assert installer.do_check() == 1


def test_install_command_exits_nonzero_without_hermes_source(tmp_path):
    env = os.environ.copy()
    env["HERMES_HOME"] = str(tmp_path)

    result = subprocess.run(
        [sys.executable, str(INSTALLER)],
        cwd=INSTALLER.parent,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "providers.py not found" in result.stderr


def test_env_var_get_and_set(tmp_path):
    installer = load_installer(tmp_path)
    installer.ENV_FILE = tmp_path / ".env"

    assert installer.get_env_var("BONZAI_API_KEY") is None
    installer.set_env_var("BONZAI_API_KEY", "sk-test-12345")
    assert installer.get_env_var("BONZAI_API_KEY") == "sk-test-12345"

    installer.set_env_var("BONZAI_API_KEY", "sk-updated-67890")
    assert installer.get_env_var("BONZAI_API_KEY") == "sk-updated-67890"


def test_configure_bonzai_defaults(tmp_path):
    installer = load_installer(tmp_path)
    installer.CONFIG_FILE = tmp_path / "config.yaml"
    installer.ENV_FILE = tmp_path / ".env"

    installer.configure_bonzai_defaults(api_key="sk-bonzai-default")
    assert installer.get_env_var("BONZAI_API_KEY") == "sk-bonzai-default"

    config = installer._load_config()
    assert config["model"]["provider"] == "bonzai"
    assert config["model"]["default"] == "gemini-3.7-flash"
    assert "io" in config["model_aliases"]
    assert config["model_aliases"]["io"]["provider"] == "bonzai"


def test_add_client_alias(tmp_path):
    installer = load_installer(tmp_path)
    installer.CONFIG_FILE = tmp_path / "config.yaml"
    installer.ENV_FILE = tmp_path / ".env"

    installer.add_client_alias("landal", "sk-landal-key", "gemini-3.7-flash")
    assert installer.get_env_var("BONZAI_LANDAL_API_KEY") == "sk-landal-key"

    config = installer._load_config()
    assert "landal" in config["model_aliases"]
    alias = config["model_aliases"]["landal"]
    assert alias["model"] == "gemini-3.7-flash"
    assert alias["provider"] == "custom"
    assert alias["base_url"] == "https://api-v2.bonzai.iodigital.com"
    assert alias["key_env"] == "BONZAI_LANDAL_API_KEY"


def test_one_click_launchers_exist():
    mac_launcher = INSTALLER.parent / "Install-Bonzai.command"
    win_launcher = INSTALLER.parent / "Install-Bonzai.cmd"
    assert mac_launcher.is_file()
    assert win_launcher.is_file()

