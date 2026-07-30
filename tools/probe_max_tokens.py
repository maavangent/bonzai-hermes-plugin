#!/usr/bin/env python3
"""Measure each Bonzai model's real completion-token ceiling.

Bonzai does not clamp an over-large ``max_tokens`` — it returns HTTP 400 with
the true limit in the message. This script reads that limit straight from the
API instead of guessing, and prints a ready-to-paste ``_MODEL_MAX_TOKENS`` dict
for ``bonzai/__init__.py``.

Only models whose ceiling is BELOW the profile's ``default_max_tokens`` need an
entry — everything else accepts the default.

Usage:
    python3 tools/probe_max_tokens.py gpt-4o gpt-4o-mini claude-opus-5
    python3 tools/probe_max_tokens.py --all      # probe the plugin's shortlist

Reads BONZAI_API_KEY from the environment, else from $HERMES_HOME/.env.
Costs one tiny completion per model, so --all is a few cents.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROBE_CEILING = 32768
ENDPOINT = "https://api-v2.bonzai.iodigital.com/v1/chat/completions"
MODELS_ENDPOINT = "https://api-v2.bonzai.iodigital.com/v1/models"


def api_key() -> str:
    var = "BONZAI_API" + "_KEY"
    key = os.environ.get(var)
    if key:
        return key
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    env = home / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith(var + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(f"No {var} found in the environment or {env}")


def ssl_context() -> ssl.SSLContext:
    # Verification stays ON; certifi's bundle avoids the macOS
    # "unable to get local issuer certificate" false negative.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def shortlist(key: str, ctx: ssl.SSLContext) -> list[str]:
    """The model ids the plugin actually shows, separator excluded."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import importlib.util
    import types

    providers = types.ModuleType("providers")
    providers.register_provider = lambda _profile: None  # type: ignore[attr-defined]
    base = types.ModuleType("providers.base")
    base.ProviderProfile = type("ProviderProfile", (), {})  # type: ignore[attr-defined]
    sys.modules.setdefault("providers", providers)
    sys.modules.setdefault("providers.base", base)

    plugin = Path(__file__).resolve().parents[1] / "bonzai" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_bonzai_probe", plugin)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    req = urllib.request.Request(
        MODELS_ENDPOINT, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        data = json.load(resp)
    ids = [m["id"] for m in (data if isinstance(data, list) else data.get("data", []))]
    return [m for m in module._build_smart_shortlist(ids) if m != module._SEPARATOR]


def probe(model: str, key: str, ctx: ssl.SSLContext) -> tuple[int | None, str]:
    body = json.dumps(
        {
            "model": model,
            "max_tokens": PROBE_CEILING,
            "messages": [{"role": "user", "content": "hi"}],
        }
    ).encode()
    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90, context=ctx) as resp:
            json.load(resp)
        return None, f"accepts {PROBE_CEILING}"
    except urllib.error.HTTPError as exc:
        text = exc.read().decode(errors="replace")
        hit = re.search(r"at most (\d+) completion tokens", text)
        if hit:
            return int(hit.group(1)), f"CAP {hit.group(1)}"
        return None, f"HTTP {exc.code}: {text[:120]}".replace("\n", " ")
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--all"]
    key, ctx = api_key(), ssl_context()
    models = shortlist(key, ctx) if ("--all" in sys.argv or not args) else args

    print(f"Probing {len(models)} model(s) with max_tokens={PROBE_CEILING}\n")
    caps: dict[str, int] = {}
    broken: list[str] = []
    for model in models:
        cap, status = probe(model, key, ctx)
        print(f"  {model:28} {status}", flush=True)
        if cap is not None:
            caps[model] = cap
        elif status.startswith("HTTP"):
            broken.append(model)

    print("\n# paste into bonzai/__init__.py")
    print("_MODEL_MAX_TOKENS: dict = {")
    for model, cap in sorted(caps.items()):
        print(f'    "{model}": {cap},')
    print("}")

    if broken:
        print(f"\n# server-side errors (not a token limit): {', '.join(broken)}")


if __name__ == "__main__":
    main()
