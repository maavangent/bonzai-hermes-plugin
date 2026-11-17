"""Import a standalone provider without leaking Hermes SDK stubs."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import patch


def load_plugin():
    providers = types.ModuleType("providers")
    setattr(providers, "register_provider", lambda _profile: None)
    base = types.ModuleType("providers.base")

    class ProviderProfile:
        default_max_tokens = None

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def invalidate_catalog_cache(self):
            pass

    setattr(base, "ProviderProfile", ProviderProfile)
    path = Path(__file__).parents[1] / "bonzai" / "__init__.py"
    spec = importlib.util.spec_from_file_location("bonzai_provider_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"providers": providers, "providers.base": base}):
        spec.loader.exec_module(module)
    return module
