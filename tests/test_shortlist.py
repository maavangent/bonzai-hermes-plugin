from __future__ import annotations

from provider_helper import load_plugin

module = load_plugin()


def leading(models, count):
    """Return the expected model-ID prefix from the flat provider list."""
    return module._build_smart_shortlist(models)[:count]


def test_anthropic_families_show_their_three_newest_versions():
    raw = [
        "claude-opus-4-6",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-opus-5-5",
        "claude-sonnet-4-5",
        "claude-sonnet-4-6",
        "claude-sonnet-5",
        "claude-sonnet-5-5",
        "claude-haiku-4-4",
        "claude-haiku-4-5",
    ]

    assert module._build_smart_shortlist(raw) == [
        "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5",
        "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-4",
        "claude-opus-4-8", "claude-sonnet-4-6",
    ]


def test_openai_keeps_supported_recent_releases_and_omits_gpt4():
    raw = ["gpt-5", "gpt-5.1", "gpt-5.4", "gpt-5.5", "gpt-4o", "gpt-4.1", "gpt-4o-mini"]

    assert module._build_smart_shortlist(raw) == ["gpt-5.5", "gpt-5.4", "gpt-5.1"]


def test_openai_o_series_are_excluded_from_the_compact_picker():
    assert module._build_smart_shortlist(["o1", "o3", "o3-mini", "o4-mini"]) == []


def test_named_variants_of_one_gpt_version_all_reach_the_flagship_tier():
    # GPT-5.6 Luna/Sol are independent tracks but both retain their live variant.
    raw = ["gpt-5.4", "gpt-5.5", "gpt-5.6-luna", "gpt-5.6-sol"]

    shown = module._build_smart_shortlist(raw)

    assert shown == ["gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.5", "gpt-5.4"]


def test_lightweight_tiers_are_excluded_from_the_compact_picker():
    raw = ["gpt-5.4", "gpt-5.5", "gpt-5.5-mini", "gpt-5.5-nano", "claude-haiku-4-5"]

    shown = module._build_smart_shortlist(raw)
    assert "gpt-5.5-mini" not in shown
    assert "gpt-5.5-nano" not in shown
    assert shown == ["claude-haiku-4-5", "gpt-5.5", "gpt-5.4"]


def test_lightweight_variants_are_excluded_from_compact_picker():
    raw = ["gpt-5.5", "gpt-5.5-mini", "gpt-5.5-nano", "gpt-5.4", "gpt-4o-mini"]

    assert module._build_smart_shortlist(raw) == ["gpt-5.5", "gpt-5.4"]


def test_provider_ids_remain_real_and_unique():
    raw = ["bonzai-executor", "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8"]

    shown = module._build_smart_shortlist(raw)

    assert set(shown) <= set(raw)
    assert len(shown) == len(set(shown))

def test_recognized_families_show_three_releases_each():
    raw = ["claude-opus-5-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7"]

    assert module._build_smart_shortlist(raw) == ["claude-opus-5-5", "claude-opus-5", "claude-opus-4-8"]


def test_older_releases_beyond_the_three_buckets_are_omitted():
    raw = ["claude-opus-5-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6"]

    shown = module._build_smart_shortlist(raw)

    assert shown == ["claude-opus-5-5", "claude-opus-5", "claude-opus-4-8"]
    assert "claude-opus-4-7" not in shown
    assert "claude-opus-4-6" not in shown


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


def test_models_with_only_two_release_buckets_stay_in_them():
    raw = ["claude-opus-5", "claude-opus-4-8"]

    assert module._build_smart_shortlist(raw) == raw


def test_models_with_no_supported_release_bucket_are_omitted():
    raw = ["gpt-5.5-mini", "gpt-5.4-mini", "gpt-4o-mini"]

    assert module._build_smart_shortlist(raw) == []


def test_unknown_models_are_not_returned_by_the_compact_picker():
    raw = ["vendor-new-model", "custom-chat-v2"]

    assert module._build_smart_shortlist(raw) == []


def test_clean_claude_id_wins_when_both_naming_orders_exist():
    raw = ["claude-4-8-opus", "claude-opus-4-8"]

    shown = module._build_smart_shortlist(raw)

    assert shown == ["claude-opus-4-8"]


def test_bonzai_aliases_lead_in_curated_order():
    raw = [
        "gpt-6-sol",
        "bonzai-architect",
        "claude-opus-5-5",
        "bonzai-explorer",
        "gpt-6.1-sol",
        "bonzai-analyst",
        "gpt-6-luna",
        "bonzai-executor",
    ]

    shown = module._build_smart_shortlist(raw)

    assert shown[:4] == [
        "bonzai-executor",
        "bonzai-analyst",
        "bonzai-explorer",
        "bonzai-architect",
    ]

def test_gpt_tracks_are_sorted_by_their_own_numeric_versions():
    assert module._tier1_family("gpt-6-luna") == ("gpt-6-luna", (6, 0))
    assert module._tier1_family("gpt-6-sol") == ("gpt-6-sol", (6, 0))
    assert module._tier1_family("gpt-6.1-sol") == ("gpt-6-sol", (6, 1))
    assert module._tier1_family("gpt-5.6-luna") == ("gpt-5-luna", (5, 6))

    gpt6 = module._build_smart_shortlist([
        "gpt-5.6-luna", "gpt-5.6-sol", "gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol",
    ])
    assert gpt6 == ["gpt-6.1-sol", "gpt-6-luna", "gpt-6-sol", "gpt-5.6-luna", "gpt-5.6-sol"]


def test_gpt_release_tracks_are_ordered_by_numeric_version():
    raw = [
        "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8",
        "gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol",
        "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.5-luna", "gpt-5.5-sol",
    ]

    shown = module._build_smart_shortlist(raw)

    assert shown == [
        "claude-opus-5-5", "gpt-6.1-sol",
        "gpt-6-luna", "gpt-6-sol", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra",
        "gpt-5.5-luna", "gpt-5.5-sol", "claude-opus-5", "claude-opus-4-8",
    ]


def test_anthropic_families_keep_three_newest_release_buckets():
    raw = [
        "claude-opus-4-5", "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8",
        "claude-opus-5", "claude-opus-5-5",
        "claude-sonnet-4-5", "claude-sonnet-4-6", "claude-sonnet-5", "claude-sonnet-5-5",
        "claude-haiku-4-4", "claude-haiku-4-5",
    ]

    shown = module._build_smart_shortlist(raw)

    assert module._build_smart_shortlist(raw) == [
        "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5",
        "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-4",
        "claude-opus-4-8", "claude-sonnet-4-6",
    ]
    assert "claude-opus-4-5" not in shown
    assert "claude-opus-4-6" not in shown
    assert "claude-opus-4-7" not in shown
    assert "claude-sonnet-4-5" not in shown


def test_shortlist_is_compact_and_has_only_real_unique_ids():
    raw = [
        "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
        "gpt-5.3", "gpt-5.4", "gpt-5.5", "gpt-5.6", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra",
        "gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol",
    ]

    shown = module._build_smart_shortlist(raw)

    assert shown == [
        "claude-opus-5-5", "gpt-6.1-sol",
        "gpt-6-luna", "gpt-6-sol", "gpt-5.6", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra",
        "gpt-5.5", "gpt-5.4", "claude-opus-5", "claude-opus-4-8",
    ]
    assert set(shown) <= set(raw)
    assert len(shown) == len(set(shown))


def test_other_families_are_sorted_globally_by_numeric_release():
    raw = [
        "gemini-2.5-pro", "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
        "glm-5", "glm-4.7", "codestral-latest", "devstral-2-123b",
    ]

    assert module._build_smart_shortlist(raw) == [
        "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-2.5-pro",
        "glm-5", "glm-4.7", "codestral-latest", "devstral-2-123b",
    ]


    raw = ["claude-opus-5-5", "bonzai-architect", "bonzai-executor", "vendor-new-model"]

    shown = module._build_smart_shortlist(raw)

    assert shown == ["bonzai-executor", "bonzai-architect", "claude-opus-5-5"]
    assert set(shown) <= set(raw)


def test_every_visible_entry_is_a_real_api_model_id():
    raw = ["bonzai-executor", "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8"]

    shown = module._build_smart_shortlist(raw)

    assert shown == raw
    assert len(shown) == len(set(shown))


def test_multi_digit_minor_versions_sort_as_integer_releases():
    assert module._build_smart_shortlist([
        "gpt-6.9-sol", "gpt-6.10-sol", "gpt-6.8-sol", "gpt-6.1-sol",
        "gemini-3.9-flash", "gemini-3.10-flash", "glm-4.9", "glm-4.10",
    ]) == [
        "gpt-6.10-sol", "gpt-6.9-sol", "gpt-6.8-sol",
        "gemini-3.10-flash", "gemini-3.9-flash", "glm-4.10", "glm-4.9",
    ]


def test_shortlist_rejects_invalid_ids_and_collapses_exact_duplicates():
    assert module._build_smart_shortlist([
        None, 42, {}, "", " gpt-6.1-sol", "gpt-6.1-sol\n", "gpt-6.1-sol", "gpt-6.1-sol",
    ]) == ["gpt-6.1-sol"]


def test_missing_bonzai_aliases_are_not_synthesized():
    raw = ["gpt-6-luna", "bonzai-analyst"]

    shown = module._build_smart_shortlist(raw)

    assert shown[0] == "bonzai-analyst"
    assert set(shown) <= set(raw)
