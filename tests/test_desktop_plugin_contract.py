"""Behaviour tests for the Desktop companion, run in Node against the real file.

tests/js/run_plugin.mjs loads key-manager/desktop/plugin.js with the SDK and
React stubbed, drives the key switch through its real handlers, and reports
every host call it made.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parents[1]
PLUGIN = REPO / "key-manager" / "desktop" / "plugin.js"
HARNESS = REPO / "tests" / "js" / "run_plugin.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is required")


@pytest.fixture(scope="module")
def report() -> dict:
    result = subprocess.run(
        ["node", "--no-warnings", str(HARNESS), str(PLUGIN)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return json.loads(result.stdout)


def _scenario(report: dict, name: str) -> dict:
    return next(item for item in report["scenarios"] if item["name"] == name)


def test_plugin_parses_as_javascript():
    subprocess.run(["node", "--check", str(PLUGIN)], check=True, capture_output=True)


def test_registers_status_menu_pane_and_palette_entry(report):
    assert report["registered"] == ["status", "manager", "focus"]


def test_a_chat_without_a_binding_uses_the_default_key(report):
    assert report["rows"] == [{"slug": "io", "active": True}, {"slug": "landal", "active": False}]


def test_switch_goes_through_the_focused_owners_profile_route(report):
    calls = _scenario(report, "accepted")["calls"]

    assert calls[0] == {"via": "routes"}
    assert calls[1] == {
        "via": "profile-rpc",
        "route": {"connectionId": "local", "mode": "local", "profile": "default", "targetProfile": "default"},
        "method": "config.set",
        "params": {"session_id": "chat-1", "key": "model", "value": "landal --session"},
    }
    assert calls[2] == {
        "via": "rest",
        "path": "/sessions/stored-chat-1",
        "method": "POST",
        "body": {"slug": "landal"},
    }


def test_unresolved_or_ambiguous_owner_never_falls_back_to_active_gateway(report):
    for name in ("no-session", "ambiguous-route"):
        calls = _scenario(report, name)["calls"]
        assert not any(call["via"] in {"rpc", "profile-rpc", "rest"} for call in calls)


def test_foreign_focused_owner_is_routed_explicitly(report):
    calls = _scenario(report, "foreign-owner")["calls"]
    assert calls[0] == {"via": "routes"}
    assert calls[1]["via"] == "profile-rpc"
    assert calls[1]["route"]["connectionId"] == "remote"
    assert calls[1]["route"]["targetProfile"] == "work"
    assert calls[1]["params"]["session_id"] == "chat-1"


def test_focus_changes_abort_before_or_after_the_owner_rpc(report):
    before = _scenario(report, "focus-changed-during-route-resolution")
    assert not any(call["via"] == "profile-rpc" for call in before["calls"])
    assert not any(call.get("path", "").startswith("/sessions/") for call in before["calls"])

    during = _scenario(report, "focus-changed-during-rpc")
    assert sum(call["via"] == "profile-rpc" for call in during["calls"]) == 1
    assert not any(call.get("path", "").startswith("/sessions/") for call in during["calls"])


def test_registered_desktop_surfaces_and_focused_session_identity(report):
    assert report["registered"] == ["status", "manager", "focus"]
    assert report["sessionAttributes"] == {
        "runtime": "chat-1", "stored": "stored-chat-1", "owner": "local"
    }


def test_binding_is_recorded_only_after_hermes_accepted_the_switch(report):
    accepted = _scenario(report, "accepted")
    assert [call["path"] for call in accepted["calls"] if call["via"] == "rest"] == ["/sessions/stored-chat-1"]
    assert accepted["calls"][2]["body"] == {"slug": "landal"}
    assert accepted["notices"][-1]["kind"] == "success"

    rejected = _scenario(report, "rejected")
    assert [call["via"] for call in rejected["calls"] if call["via"] in {"rpc", "profile-rpc", "rest"}] == ["profile-rpc"]
    assert rejected["notices"] == [{"kind": "error", "message": "Could not switch key: Unknown model alias"}]


def test_switch_during_a_reply_is_reported_as_deferred(report):
    deferred = _scenario(report, "deferred")
    assert deferred["calls"][-1]["path"] == "/sessions/stored-chat-1"
    assert "after the current reply" in deferred["notices"][-1]["message"]


def test_no_focused_chat_changes_nothing(report):
    no_session = _scenario(report, "no-session")
    assert no_session["calls"] == []
    assert no_session["notices"][0]["kind"] == "warning"
