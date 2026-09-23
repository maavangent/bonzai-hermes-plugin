from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


providers = types.ModuleType("providers")
providers.register_provider = lambda _profile: None  # type: ignore[attr-defined]
base = types.ModuleType("providers.base")


class ProviderProfile:
    default_max_tokens = None

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def get_max_tokens(self, model):
        return self.default_max_tokens


base.ProviderProfile = ProviderProfile  # type: ignore[attr-defined]
sys.modules["providers"] = providers
sys.modules["providers.base"] = base

PLUGIN = Path(__file__).parents[1] / "bonzai" / "__init__.py"
spec = importlib.util.spec_from_file_location("bonzai_maxtokens_test", PLUGIN)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_models_with_no_measured_lower_ceiling_keep_the_default():
    # The latest probe accepted 32768 for every model in the 40-model shortlist.
    assert module.bonzai.get_max_tokens("gpt-4o") == 32768
    assert module.bonzai.get_max_tokens("gpt-4o-mini") == 32768


def test_models_without_a_known_ceiling_keep_the_generous_default():
    assert module.bonzai.get_max_tokens("claude-opus-5") == 32768
    assert module.bonzai.get_max_tokens("gpt-4.1") == 32768
    assert module.bonzai.get_max_tokens("glm-5") == 32768


def test_an_unknown_future_model_keeps_the_default_rather_than_being_capped():
    assert module.bonzai.get_max_tokens("some-model-shipped-next-month") == 32768


def test_a_missing_model_name_does_not_raise():
    assert module.bonzai.get_max_tokens(None) == 32768


def test_date_pinned_and_routed_spellings_keep_the_default():
    # The picker hides these, but a user can still have one pinned in config.
    assert module.bonzai.get_max_tokens("gpt-4o-2024-08-06") == 32768
    assert module.bonzai.get_max_tokens("gpt-4o-mini-bedrock") == 32768


def test_every_capped_entry_is_below_the_profile_default():
    # A cap at or above the default would be pointless config noise.
    for model, cap in module._MODEL_MAX_TOKENS.items():
        assert cap < module.bonzai.default_max_tokens, model


def test_declared_gemini_context_window_is_hermes_compatible():
    assert module.bonzai.model_capabilities["gemini-3.7-flash"]["context_window"] >= 64_000
