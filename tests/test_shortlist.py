from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


# Load the standalone plugin without requiring a full Hermes install.
providers = types.ModuleType("providers")
providers.register_provider = lambda _profile: None  # type: ignore[attr-defined]
base = types.ModuleType("providers.base")


class ProviderProfile:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


base.ProviderProfile = ProviderProfile  # type: ignore[attr-defined]
sys.modules.setdefault("providers", providers)
sys.modules.setdefault("providers.base", base)

PLUGIN = Path(__file__).parents[1] / "bonzai" / "__init__.py"
spec = importlib.util.spec_from_file_location("bonzai_plugin_test", PLUGIN)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SEPARATOR = module._SEPARATOR


def tier1(models):
    """The flagship tier: everything before the separator."""
    shown = module._build_smart_shortlist(models)
    return shown[: shown.index(SEPARATOR)] if SEPARATOR in shown else shown


def test_anthropic_families_show_their_two_newest_versions():
    raw = [
        "claude-opus-4-6",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-sonnet-4-5",
        "claude-sonnet-4-6",
        "claude-sonnet-5",
        "claude-haiku-4-4",
        "claude-haiku-4-5",
    ]

    assert tier1(raw) == [
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        "claude-haiku-4-4",
    ]


def test_openai_families_show_their_two_newest_versions():
    raw = [
        "gpt-5",
        "gpt-5.1",
        "gpt-5.4",
        "gpt-5.5",
        "gpt-4o",
        "gpt-4.1",
        "o1",
        "o3",
        "o3-mini",
        "o4-mini",
    ]

    assert tier1(raw) == ["gpt-5.5", "gpt-5.4", "gpt-4.1", "gpt-4o", "o3", "o1"]


def test_named_variants_of_one_gpt_version_all_reach_the_flagship_tier():
    # gpt-5.6 ships as three named variants; they are one version, so the two
    # newest versions are 5.6 (all variants) and 5.5.
    raw = ["gpt-5.4", "gpt-5.5", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"]

    assert tier1(raw) == [
        "gpt-5.6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.5",
    ]


def test_lightweight_tiers_stay_out_of_the_flagship_tier():
    raw = ["gpt-5.5", "gpt-5.5-mini", "gpt-5.5-nano", "claude-haiku-4-5"]

    flagships = tier1(raw)

    assert "gpt-5.5-mini" not in flagships
    assert "gpt-5.5-nano" not in flagships
    # Still reachable below the separator.
    assert "gpt-5.5-mini" in module._build_smart_shortlist(raw)


def test_every_shown_entry_is_a_real_api_model_id():
    raw = ["claude-opus-5", "claude-opus-4-8", "gpt-5.6-sol", "gpt-5.5", "glm-5"]

    shown = module._build_smart_shortlist(raw)

    assert set(shown) - {SEPARATOR} <= set(raw)


def test_older_versions_remain_reachable_below_the_separator():
    raw = ["claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6"]

    shown = module._build_smart_shortlist(raw)

    assert "claude-opus-4-7" in shown
    assert "claude-opus-4-6" in shown
    assert shown.index(SEPARATOR) < shown.index("claude-opus-4-7")


def test_version_first_claude_ids_without_a_clean_alias_are_hidden():
    raw = [
        "claude-haiku-4-5",
        "claude-3-haiku",
        "claude-sonnet-4-6",
        "claude-4-sonnet",
    ]

    shown = module._build_smart_shortlist(raw)

    assert "claude-haiku-4-5" in shown
    assert "claude-sonnet-4-6" in shown
    assert "claude-3-haiku" not in shown
    assert "claude-4-sonnet" not in shown


def test_clean_claude_id_wins_when_both_naming_orders_exist():
    raw = ["claude-4-8-opus", "claude-opus-4-8"]

    shown = module._build_smart_shortlist(raw)

    assert shown == ["claude-opus-4-8"]
