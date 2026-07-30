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


def test_models_with_a_lower_ceiling_get_their_measured_cap():
    # Measured against the live API: sending 32768 to these returns
    # HTTP 400 "This model supports at most 16384 completion tokens".
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


def test_date_pinned_and_routed_spellings_resolve_to_the_same_cap():
    # The picker hides these, but a user can still have one pinned in config.
    assert module.bonzai.get_max_tokens("gpt-4o-2024-08-06") == 16384
    assert module.bonzai.get_max_tokens("gpt-4o-mini-bedrock") == 16384


def test_every_capped_entry_is_below_the_profile_default():
    # A cap at or above the default would be pointless config noise.
    for model, cap in module._MODEL_MAX_TOKENS.items():
        assert cap < module.bonzai.default_max_tokens, model
