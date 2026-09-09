from pathlib import Path


PLUGIN = Path(__file__).parents[1] / "key-manager" / "desktop" / "plugin.js"


def test_desktop_plugin_imports_every_sdk_hook_it_uses():
    source = PLUGIN.read_text()

    assert "useValue," in source.split('from \"@hermes/plugin-sdk\"')[0]


def test_status_chip_is_an_interactive_menu_entrypoint():
    source = PLUGIN.read_text()

    assert 'variant: "menu"' in source
    assert "menuContent:" in source
    assert "jsx(Manager" in source


def test_status_chip_tracks_session_provider_events():
    source = PLUGIN.read_text()

    assert 'host.onEvent("session.info"' in source
    assert 'provider === "bonzai"' in source


def test_desktop_plugin_uses_generic_session_credential_rpc_contract():
    source = PLUGIN.read_text()

    assert 'host.request("session.credential.set"' in source
    assert 'host.request("session.credential.clear"' in source
    assert "host.state.activeSessionId" in source
    assert 'provider: "bonzai"' in source
    assert "credential_id:" in source


def test_desktop_plugin_exposes_automatic_and_pinned_session_modes():
    source = PLUGIN.read_text()

    assert 'value: "automatic"' in source
    assert 'children: "Automatic rotation"' in source
    assert "credential_binding" in source
    assert "running" in source
    assert "Wait until the current turn finishes" in source
    assert "eventSessionId !== activeSessionId" in source
