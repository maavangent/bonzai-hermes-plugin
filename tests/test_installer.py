from __future__ import annotations

import importlib.util
import json
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
    assert yaml.safe_load(MANIFEST.read_text())["version"] == "2.11.0"


def load_installer(home: Path):
    """Import install.py with HERMES_HOME pointed at a temp dir."""
    sys.modules.pop("bonzai_installer_test", None)
    spec = importlib.util.spec_from_file_location("bonzai_installer_test", INSTALLER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # install.py resolves paths at import time; retarget them at the temp home.
    module.HERMES_HOME = home
    module.HERMES_ROOT = module.resolve_hermes_root(home)
    module.PLUGIN_DIR = home / "plugins" / "model-providers" / "bonzai"
    module.KEY_MANAGER_DIR = home / "plugins" / "bonzai-key-manager"
    module.DESKTOP_PLUGIN_FILE = home / "desktop-plugins" / "bonzai-key-manager" / "plugin.js"
    module.PROVIDERS_FILE = home / "hermes-agent" / "hermes_cli" / "providers.py"
    module.CACHE_FILE = home / "provider_models_cache.json"
    module.CONFIG_FILE = home / "config.yaml"
    module.ENV_FILE = home / ".env"
    return module


@pytest.mark.parametrize("command", ["do_install", "do_uninstall"])
@pytest.mark.parametrize("invalid_config", [
    "[not, a, mapping]", "plugins: wrong", "plugins:\n  enabled: wrong",
    "plugins:\n  enabled: [{}]", "model: []", "model_aliases: []",
])
def test_config_preflight_preserves_existing_files(env, command, invalid_config):
    _home, installer, providers = env
    installer.CONFIG_FILE.write_text(invalid_config)
    installer.PLUGIN_DIR.mkdir(parents=True)
    marker = installer.PLUGIN_DIR / "existing.txt"
    marker.write_text("keep me")
    before = providers.read_bytes()

    with pytest.raises(RuntimeError, match="config|mapping|lists|strings"):
        getattr(installer, command)()

    assert marker.read_text() == "keep me"
    assert installer.CONFIG_FILE.read_text() == invalid_config
    assert providers.read_bytes() == before


def test_install_preflights_missing_yaml_before_replacing_files(env, monkeypatch):
    _home, installer, _providers = env
    installer.PLUGIN_DIR.mkdir(parents=True)
    marker = installer.PLUGIN_DIR / "existing.txt"
    marker.write_text("keep me")
    monkeypatch.setattr(installer, "yaml", None)
    with pytest.raises(RuntimeError, match="PyYAML"):
        installer.do_install()
    assert marker.read_text() == "keep me"


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


def test_missing_providers_file_skips_legacy_overlay(tmp_path):
    installer = load_installer(tmp_path)
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


def test_native_provider_resolution_removes_legacy_overlay(tmp_path):
    installer = load_installer(tmp_path)
    providers = installer.PROVIDERS_FILE
    providers.parent.mkdir(parents=True)
    native_source = '''
HERMES_OVERLAYS = {
    "bonzai": HermesOverlay(
        transport="openai_chat",
        auth_type="api_key",
    ),
}
def _plugin_profile_pdef(name):
    return None
def resolve_provider_full(name):
    pdef = _plugin_profile_pdef(name)
    return pdef if pdef is not None and pdef.id != "custom" else None
'''
    providers.write_text(native_source)

    installer.add_overlay()

    assert '"bonzai": HermesOverlay(' not in providers.read_text()
    assert installer.overlay_missing() is False


def test_native_resolution_detection_ignores_formatting(env):
    _home, installer, providers = env
    providers.write_text('''
def _plugin_profile_pdef(name):
    return get_provider_profile(name)
def resolve_provider_full(name):
    resolved = _plugin_profile_pdef(name)
    if resolved is not None:
        return resolved
    return None
''')
    before = providers.read_bytes()
    assert installer._native_provider_resolution_supported()
    installer.add_overlay()
    assert providers.read_bytes() == before


def test_native_resolution_detection_does_not_trust_comments(env):
    _home, installer, providers = env
    providers.write_text(PROVIDERS_STUB + '''
# def resolve_provider_full(
# _plugin_profile_pdef
# return pdef if pdef is not None and pdef.id != "custom" else None
''')
    assert not installer._native_provider_resolution_supported()


def test_providers_source_discovered_from_current_runtime(tmp_path, monkeypatch):
    installer = load_installer(tmp_path)
    runtime = tmp_path / "runtime"
    source = runtime / "hermes_cli" / "providers.py"
    source.parent.mkdir(parents=True)
    source.write_text("# source only")
    monkeypatch.setattr(installer.sys, "prefix", str(runtime / ".venv"))
    assert installer.resolve_providers_file(tmp_path) == source


@pytest.mark.parametrize("venv", [".venv", "venv"])
@pytest.mark.parametrize("executable", ["bin/python", "Scripts/python.exe"])
def test_find_hermes_python_supports_current_venv_names(tmp_path, monkeypatch, venv, executable):
    installer = load_installer(tmp_path)
    monkeypatch.setattr(installer.Path, "home", lambda: tmp_path)
    candidate = tmp_path / "hermes-agent" / venv / executable
    candidate.parent.mkdir(parents=True)
    candidate.touch()
    assert installer._find_hermes_python() == candidate


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
    installer.configure_bonzai_defaults("synthetic-value")
    installer.do_install()

    assert installer.do_check() == 0

    installer.DESKTOP_PLUGIN_FILE.unlink()
    assert installer.do_check() == 1


def test_check_rejects_key_manager_with_wrong_manifest_kind(env, capsys):
    _home, installer, _providers = env
    installer.configure_bonzai_defaults("synthetic-value")
    installer.do_install()
    assert installer.do_check() == 0
    (installer.KEY_MANAGER_DIR / "plugin.yaml").write_text("name: bonzai-key-manager\nkind: standalone\n")
    assert installer.do_check() == 1
    assert "kind: backend" in capsys.readouterr().out


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


def test_install_command_succeeds_without_hermes_source(tmp_path):
    env = os.environ.copy()
    env["HERMES_HOME"] = str(tmp_path)

    result = subprocess.run(
        [sys.executable, str(INSTALLER)],
        cwd=INSTALLER.parent,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "skipping legacy overlay" in result.stdout


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
    assert config["model"]["default"] == "gpt-6-luna"
    assert "io" in config["model_aliases"]
    assert config["model_aliases"]["io"]["provider"] == "bonzai"


@pytest.mark.parametrize("model", [
    {"provider": "openai", "default": "gpt-model", "base_url": "https://other.example", "api_key": "${OTHER}"},
    {"default": "other-model"}, "other-model",
])
def test_install_preserves_existing_non_bonzai_model(env, model, capsys):
    _home, installer, _providers = env
    installer.CONFIG_FILE.write_text(yaml.safe_dump({"model": model}))
    installer.do_install()
    config = installer._load_config()
    assert config["model"] == model
    assert config["model_aliases"]["io"]["provider"] == "bonzai"
    assert "as your default model" not in capsys.readouterr().out


def test_configure_defaults_preflights_before_writing_secret(tmp_path):
    installer = load_installer(tmp_path)
    installer.CONFIG_FILE.write_text("model_aliases: []")
    with pytest.raises(RuntimeError, match="mapping"):
        installer.configure_bonzai_defaults(api_key="synthetic-value")
    assert not installer.ENV_FILE.exists()


def test_add_client_alias_refuses_existing_alias_before_writing_secret(tmp_path):
    installer = load_installer(tmp_path)
    installer.CONFIG_FILE = tmp_path / "config.yaml"
    installer.ENV_FILE = tmp_path / ".env"
    installer.CONFIG_FILE.write_text(yaml.safe_dump({
        "model_aliases": {"landal": {"model": "keep-me", "provider": "bonzai"}}
    }))
    installer.ENV_FILE.write_text("BONZAI_LANDAL_API_KEY=existing-secret\n")

    with pytest.raises(ValueError, match="already exists"):
        installer.add_client_alias("Landal", "replacement-secret", "claude-sonnet-5")

    assert installer.get_env_var("BONZAI_LANDAL_API_KEY") == "existing-secret"
    assert installer._load_config()["model_aliases"]["landal"]["model"] == "keep-me"


@pytest.mark.parametrize("assignment", ["BONZAI_CLIENT_API_KEY=orphan", "export BONZAI_CLIENT_API_KEY=orphan", "BONZAI_CLIENT_API_KEY="])
def test_alias_rejects_existing_orphan_env_assignment(tmp_path, assignment):
    installer = load_installer(tmp_path)
    installer.ENV_FILE.write_text("# keep\n" + assignment + "\n")
    before = installer.ENV_FILE.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        installer.add_client_alias("Client", "replacement-synthetic")
    assert installer.ENV_FILE.read_bytes() == before
    assert not installer.CONFIG_FILE.exists()


@pytest.mark.parametrize("initial_files", [False, True])
@pytest.mark.parametrize("failure", ["before_save", "after_save"])
def test_alias_save_failure_rolls_back_exact_files(tmp_path, monkeypatch, initial_files, failure):
    installer = load_installer(tmp_path)
    if initial_files:
        installer.ENV_FILE.write_bytes(b'# env note\r\nOTHER=value\r\n')
        installer.CONFIG_FILE.write_bytes(b'# config note\nmodel: other\n')
        installer.ENV_FILE.chmod(0o640)
        installer.CONFIG_FILE.chmod(0o600)
    paths = (installer.ENV_FILE, installer.CONFIG_FILE)
    before = [(p.read_bytes(), p.stat().st_mode & 0o777) if p.exists() else None for p in paths]
    original = installer._save_config
    def fail_save(config):
        if failure == "after_save":
            original(config)
        raise OSError("synthetic config failure")
    monkeypatch.setattr(installer, "_save_config", fail_save)
    with pytest.raises(OSError, match="synthetic config failure"):
        installer.add_client_alias("Client", "synthetic-client")
    after = [(p.read_bytes(), p.stat().st_mode & 0o777) if p.exists() else None for p in paths]
    assert after == before


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


@pytest.mark.parametrize("mode", ["fresh", "replace", "alias"])
def test_secret_prompts_use_hidden_input(tmp_path, monkeypatch, mode):
    installer = load_installer(tmp_path)
    if mode == "replace":
        installer.set_env_var("BONZAI_API_KEY", "old-synthetic")
    responses = iter(["3"] if mode == "replace" else ["Client", ""])
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    import getpass
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "new-synthetic")
    if mode == "alias":
        installer.interactive_add_alias()
        assert installer.get_env_var("BONZAI_CLIENT_API_KEY") == "new-synthetic"
    else:
        assert installer.prompt_api_key_if_needed() == "new-synthetic"


@pytest.mark.parametrize("replacement", ["", "new-synthetic", None])
def test_move_to_client_requires_replacement_before_moving(tmp_path, monkeypatch, replacement):
    installer = load_installer(tmp_path)
    installer.set_env_var("BONZAI_API_KEY", "client-synthetic")
    responses = iter(["2", "Client", ""])
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    import getpass
    def hidden(prompt):
        if replacement is None:
            raise EOFError
        return replacement
    monkeypatch.setattr(getpass, "getpass", hidden)
    result = installer.prompt_api_key_if_needed()
    if replacement:
        installer.configure_bonzai_defaults(result)
        assert installer.get_env_var("BONZAI_CLIENT_API_KEY") == "client-synthetic"
        assert installer.get_env_var("BONZAI_API_KEY") == replacement
    else:
        assert result is None
        assert not installer.CONFIG_FILE.exists()
        assert installer.get_env_var("BONZAI_CLIENT_API_KEY") is None
        assert installer.get_env_var("BONZAI_API_KEY") == "client-synthetic"


@pytest.mark.parametrize("failure", ["alias_save", "default_before_write", "default_after_write"])
def test_move_write_failure_restores_exact_env_and_config(tmp_path, monkeypatch, failure):
    installer = load_installer(tmp_path)
    installer.ENV_FILE.write_bytes(b'# note\r\nBONZAI_API_KEY=client-synthetic\r\nOTHER=keep\r\n')
    installer.ENV_FILE.chmod(0o640)
    installer.CONFIG_FILE.write_bytes(b'# notes\nmodel: other-model\n')
    paths = (installer.ENV_FILE, installer.CONFIG_FILE)
    before = [(p.read_bytes(), p.stat().st_mode & 0o777) for p in paths]
    responses = iter(["2", "Client", ""])
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    monkeypatch.setattr(installer.getpass, "getpass", lambda prompt: "replacement-synthetic")
    save = installer._save_config
    write = installer.set_env_var
    def failing_save(config):
        save(config)
        if failure == "alias_save":
            raise OSError("synthetic move failure")
    def failing_write(name, value):
        if name == "BONZAI_API_KEY" and failure == "default_before_write":
            raise OSError("synthetic move failure")
        write(name, value)
        if name == "BONZAI_API_KEY" and failure == "default_after_write":
            raise OSError("synthetic move failure")
    monkeypatch.setattr(installer, "_save_config", failing_save)
    monkeypatch.setattr(installer, "set_env_var", failing_write)
    with pytest.raises(OSError, match="synthetic move failure"):
        installer.prompt_api_key_if_needed()
    assert [(p.read_bytes(), p.stat().st_mode & 0o777) for p in paths] == before


def test_mac_launcher_prefers_dotvenv_and_preserves_failure_status(tmp_path):
    import shutil
    launcher = tmp_path / "Install.command"
    shutil.copy2(INSTALLER.parent / "Install-Bonzai-Model-Provider.command", launcher)
    runtime = tmp_path / ".hermes" / "hermes-agent" / ".venv" / "bin" / "python3"
    runtime.parent.mkdir(parents=True)
    runtime.write_text('#!/bin/sh\nprintf "selected-dotvenv\\n"\nexit 7\n')
    runtime.chmod(0o755)
    environment = dict(os.environ, HOME=str(tmp_path), HERMES_HOME=str(tmp_path / ".hermes"))
    result = subprocess.run(["bash", str(launcher)], env=environment, input="x", capture_output=True, text=True)
    assert "selected-dotvenv" in result.stdout
    assert result.returncode == 7


def test_windows_launcher_detects_dotvenv_and_propagates_exit_code():
    script = (INSTALLER.parent / "Install-Bonzai-Model-Provider.cmd").read_text()
    assert r"hermes-agent\.venv\Scripts\python.exe" in script
    assert "exit /b" in script.lower()


def test_one_click_launchers_exist():
    mac_launcher = INSTALLER.parent / "Install-Bonzai-Model-Provider.command"
    win_launcher = INSTALLER.parent / "Install-Bonzai-Model-Provider.cmd"
    assert mac_launcher.is_file()
    assert win_launcher.is_file()


def test_env_writes_are_owner_only_and_deduplicate(tmp_path):
    installer = load_installer(tmp_path)
    installer.ENV_FILE = tmp_path / ".env"
    installer.ENV_FILE.write_text("# note\nexport BONZAI_API_KEY=old\nOTHER=1\nBONZAI_API_KEY=dup\n")
    installer.ENV_FILE.chmod(0o644)

    installer.set_env_var("BONZAI_API_KEY", "new-value\n")

    assert installer.ENV_FILE.read_text() == "# note\nBONZAI_API_KEY=new-value\nOTHER=1\n"
    assert installer.ENV_FILE.stat().st_mode & 0o077 == 0


def test_client_alias_uses_the_key_manager_slug_and_rejects_reserved_names(tmp_path):
    installer = load_installer(tmp_path)
    installer.ENV_FILE = tmp_path / ".env"

    assert installer.add_client_alias("Landal  NL", "client-value") == "landal-nl"
    alias = installer._load_config()["model_aliases"]["landal-nl"]
    assert alias["label"] == "Landal  NL"
    assert alias["key_env"] == "BONZAI_LANDAL_NL_API_KEY"

    for reserved in ("iO", "default", "Bonzai"):
        with pytest.raises(ValueError, match="reserved"):
            installer.add_client_alias(reserved, "client-value")
    assert "io" not in installer._load_config()["model_aliases"]


def test_config_edits_keep_user_comments_when_hermes_is_available(tmp_path):
    installer = load_installer(tmp_path)
    if installer._hermes_config_writer() is None:
        pytest.skip("run with Hermes' own Python to exercise its config writer")
    installer.CONFIG_FILE.write_text("# my notes\nmodel:\n  provider: openrouter  # keep\n")

    installer.configure_bonzai_defaults()

    text = installer.CONFIG_FILE.read_text()
    assert "# my notes" in text
    assert "# keep" in text
    assert installer._load_config()["model"]["provider"] == "openrouter"


def test_config_is_never_rewritten_without_a_yaml_parser(tmp_path, monkeypatch):
    installer = load_installer(tmp_path)
    original = "model:\n  provider: openrouter\n  nested:\n    deep: true\n"
    installer.CONFIG_FILE.write_text(original)
    monkeypatch.setattr(installer, "yaml", None)

    with pytest.raises(RuntimeError, match="PyYAML is not available"):
        installer.configure_bonzai_defaults()

    assert installer.CONFIG_FILE.read_text() == original


def test_check_flags_client_keys_left_in_the_credential_pool(env):
    home, installer, _providers = env
    installer.configure_bonzai_defaults("synthetic-value")
    installer.do_install()
    assert installer.do_check() == 0

    (home / "auth.json").write_text(json.dumps({"credential_pool": {"bonzai": [
        {"id": "a", "source": "env:BONZAI_API_KEY"},
        {"id": "b", "source": "manual", "label": "Landal"},
    ]}}))

    assert installer.pooled_client_keys() == 1
    assert installer.do_check() == 1


@pytest.mark.parametrize("missing", [
    ".env", "plugins/model-providers/bonzai/__init__.py",
    "plugins/model-providers/bonzai/plugin.yaml",
    "plugins/bonzai-key-manager/dashboard/plugin_api.py",
    "plugins/bonzai-key-manager/plugin.yaml",
])
def test_health_check_rejects_missing_required_artifacts(env, missing, capsys):
    home, installer, _providers = env
    installer.configure_bonzai_defaults("synthetic-value")
    installer.do_install()
    assert installer.do_check() == 0
    capsys.readouterr()
    (home / missing).unlink()
    assert installer.do_check() == 1
    assert "everything is healthy" not in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["backend", "standalone"])
def test_health_check_rejects_wrong_provider_manifest_kind(env, kind):
    _home, installer, _providers = env
    installer.configure_bonzai_defaults("synthetic-value")
    installer.do_install()
    (installer.PLUGIN_DIR / "plugin.yaml").write_text(f"name: bonzai\nkind: {kind}\n")
    assert installer.do_check() == 1


def test_health_check_detects_stale_manifest(env):
    _home, installer, _providers = env
    installer.configure_bonzai_defaults("synthetic-value")
    installer.do_install()
    manifest = installer.PLUGIN_DIR / "plugin.yaml"
    manifest.write_text(manifest.read_text() + "\n# stale copy\n")
    assert installer.do_check() == 1


def test_health_check_reports_invalid_config_without_traceback(env, capsys):
    _home, installer, _providers = env
    installer.configure_bonzai_defaults("synthetic-value")
    installer.do_install()
    installer.CONFIG_FILE.write_text("plugins: []")
    assert installer.do_check() == 1
    assert "mapping" in capsys.readouterr().out


def test_check_flags_a_stale_installed_copy(env):
    _home, installer, _providers = env
    installer.do_install()
    assert installer.stale_installed_files() == []

    installer.DESKTOP_PLUGIN_FILE.write_text("// older build")

    assert installer.stale_installed_files() == ["desktop-plugins/bonzai-key-manager/plugin.js"]
    assert installer.do_check() == 1

