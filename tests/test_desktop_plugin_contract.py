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


def test_switch_goes_through_the_session_scoped_model_rpc(report):
    calls = _scenario(report, "accepted")["calls"]

    assert calls[0] == {
        "via": "rpc",
        "method": "config.set",
        "params": {"session_id": "chat-1", "key": "model", "value": "landal --session"},
    }


def test_binding_is_recorded_only_after_hermes_accepted_the_switch(report):
    accepted = _scenario(report, "accepted")
    assert [call.get("path") or call["method"] for call in accepted["calls"]] == ["config.set", "/sessions/chat-1"]
    assert accepted["calls"][1]["body"] == {"slug": "landal"}
    assert accepted["notices"][-1]["kind"] == "success"

    rejected = _scenario(report, "rejected")
    assert [call.get("path") for call in rejected["calls"] if call["via"] == "rest"] == []
    assert rejected["notices"] == [{"kind": "error", "message": "Could not switch key: Unknown model alias"}]


def test_switch_during_a_reply_is_reported_as_deferred(report):
    deferred = _scenario(report, "deferred")
    assert deferred["calls"][-1]["path"] == "/sessions/chat-1"
    assert "after the current reply" in deferred["notices"][-1]["message"]


def test_no_focused_chat_changes_nothing(report):
    no_session = _scenario(report, "no-session")
    assert no_session["calls"] == []
    assert no_session["notices"][0]["kind"] == "warning"
