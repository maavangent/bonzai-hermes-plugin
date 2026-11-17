from __future__ import annotations

from provider_helper import load_plugin

module = load_plugin()


def test_models_with_catalog_reported_lower_ceiling_keep_their_cap():
    # The catalog reports 16,384 for these models; keep the conservative cap
    # even though a gateway probe accepted a 32,768 request.
    assert module.bonzai.get_max_tokens("gpt-4o") == 16384
    assert module.bonzai.get_max_tokens("gpt-4o-mini") == 16384


def test_models_without_a_known_ceiling_keep_the_generous_default():
    assert module.bonzai.get_max_tokens("claude-opus-5") == 32768
    assert module.bonzai.get_max_tokens("gpt-4.1") == 32768
    assert module.bonzai.get_max_tokens("glm-5") == 32768


def test_an_unknown_future_model_keeps_the_default_rather_than_being_capped():
    assert module.bonzai.get_max_tokens("some-model-shipped-next-month") == 32768


def test_a_missing_model_name_does_not_raise():
    assert module.bonzai.get_max_tokens(None) == 32768


def test_date_pinned_and_routed_spellings_resolve_to_the_catalog_cap():
    # The picker hides these, but a user can still have one pinned in config.
    assert module.bonzai.get_max_tokens("gpt-4o-2024-08-06") == 16384
    assert module.bonzai.get_max_tokens("gpt-4o-mini-bedrock") == 16384


def test_every_capped_entry_is_below_the_profile_default():
    # A cap at or above the default would be pointless config noise.
    for model, cap in module._MODEL_MAX_TOKENS.items():
        assert cap < module.bonzai.default_max_tokens, model


def test_declared_gemini_context_window_is_hermes_compatible():
    assert module.bonzai.model_capabilities["gemini-3.7-flash"]["context_window"] >= 64_000


def test_bonzai_vertex_gateway_error_is_server_error():
    verdict = module._classify_bonzai_error(
        RuntimeError("HTTP 500"),
        status_code=500,
        message="litellm.APIConnectionError: unable to load vertex credentials from environment",
        model="gemini-3.7-flash",
    )
    assert verdict["reason"] == "server_error"
    assert verdict["should_fallback"] is False
    assert verdict["error_context"]["upstream_failure"] == "credential_configuration"


def test_unrelated_bonzai_error_is_left_to_hermes():
    assert module._classify_bonzai_error(RuntimeError("bad request"), status_code=400) is None


def test_catalog_preserves_validated_context_correction():
    fresh = load_plugin()
    capabilities = fresh._catalog_capabilities([
        {"id": "gemini-3.7-flash", "mode": "chat", "max_input_tokens": 8192, "max_output_tokens": 8192},
    ])
    assert capabilities["gemini-3.7-flash"] == {
        "context_window": 1_048_576, "max_output_tokens": 8192,
    }


def test_credential_catalog_limits_stay_local_to_the_snapshot():
    fresh = load_plugin()
    capabilities = fresh._catalog_capabilities([
        {"id": "gpt-6.1-sol", "mode": "chat", "max_output_tokens": 4096},
        {"id": "claude-opus-5", "mode": "chat", "max_output_tokens": 128_000},
        {"id": "gpt-4o", "mode": "chat", "max_output_tokens": 8192},
    ])
    assert capabilities["gpt-6.1-sol"]["max_output_tokens"] == 4096
    assert fresh.bonzai.get_max_tokens("gpt-6.1-sol") == 32768
    assert fresh.bonzai.get_max_tokens("claude-opus-5") == 32768
    assert capabilities["gpt-4o"]["max_output_tokens"] == 8192
    assert fresh.bonzai.get_max_tokens("gpt-4o") == 16384


def test_invalid_catalog_capabilities_are_not_imported():
    fresh = load_plugin()
    capabilities = fresh._catalog_capabilities([
        {"id": "gpt-6.1-sol", "mode": "chat", "max_input_tokens": True, "max_output_tokens": True},
        {"id": "bad id", "mode": "chat", "max_input_tokens": 64000},
        {"id": "gpt-6.2-sol", "mode": "chat", "max_input_tokens": -1, "max_output_tokens": "8192"},
    ])
    assert "gpt-6.1-sol" not in capabilities
    assert "bad id" not in capabilities
    assert "gpt-6.2-sol" not in capabilities


def test_capability_probe_marks_provider_vision_support():
    assert module.bonzai.supports_vision is True
    assert module.bonzai.supports_vision_tool_messages is True
    capabilities = module._catalog_capabilities([
        {"id": "claude-sonnet-5", "mode": "chat", "max_input_tokens": 1_000_000, "max_output_tokens": 128_000},
        {"id": "image-model", "mode": "image_generation", "max_input_tokens": 32_000},
    ])
    assert capabilities["claude-sonnet-5"] == {
        "context_window": 1_000_000,
        "max_output_tokens": 128_000,
    }
    assert "image-model" not in capabilities
