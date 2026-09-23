from pathlib import Path


PLUGIN = Path(__file__).parents[1] / "key-manager" / "desktop" / "plugin.js"


def test_desktop_plugin_imports_every_sdk_hook_it_uses():
    source = PLUGIN.read_text()

    assert "useValue," in source.split('from "@hermes/plugin-sdk"')[0]


def test_status_chip_is_an_interactive_menu_entrypoint():
    source = PLUGIN.read_text()

    assert 'variant: "menu"' in source
    assert "menuContent:" in source
    assert "jsx(Manager" in source


def test_status_chip_tracks_active_session():
    source = PLUGIN.read_text()

    assert "host.state.focusedSessionId" in source
    assert 'request(ctx, "/sessions")' in source


def test_desktop_plugin_uses_slash_exec_contract():
    source = PLUGIN.read_text()

    assert 'host.request("slash.exec"' in source
    assert "`/model ${slug}`" in source
    assert "host.state.focusedSessionId" in source
    assert "session_id:" in source


def test_desktop_plugin_exposes_client_selection_and_add_flows():
    source = PLUGIN.read_text()

    assert "Active In This Chat" in source
    assert "Active in chat" in source
    assert "+ Add Client Key" in source
    assert "entries.map(" in source
