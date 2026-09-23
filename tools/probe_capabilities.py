#!/usr/bin/env python3
"""Probe Bonzai chat capabilities without executing real tools.

Usage:
    python3 tools/probe_capabilities.py --models claude-sonnet-5 gemini-3.7-flash
    python3 tools/probe_capabilities.py --all

Reads BONZAI_API_KEY from the environment or ``$HERMES_HOME/.env``. The probe
uses harmless requests: a tool definition is supplied but never executed, and
vision uses a 1x1 transparent PNG. Results are written to JSON when ``--out``
is supplied.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://api-v2.bonzai.iodigital.com/v1/chat/completions"
MODELS_ENDPOINT = "https://api-v2.bonzai.iodigital.com/v1/models"
TINY_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="


def api_key() -> str:
    value = os.getenv("BONZAI_API_KEY")
    if value:
        return value
    home = Path(os.getenv("HERMES_HOME") or Path.home() / ".hermes")
    env_file = home / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("BONZAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"No BONZAI_API_KEY found in environment or {env_file}")


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def request_json(body: dict, key: str, ctx: ssl.SSLContext) -> tuple[int, dict | str]:
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90, context=ctx) as response:
            return int(response.status), json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        text = exc.read().decode(errors="replace")
        return int(exc.code), text[:500]
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def message_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    message = choices[0].get("message", {}) if choices else {}
    content = message.get("content")
    return content if isinstance(content, str) else json.dumps(message, sort_keys=True)


def probe_tools(model: str, key: str, ctx: ssl.SSLContext) -> dict:
    status, payload = request_json({
        "model": model,
        "max_tokens": 32,
        "messages": [{"role": "user", "content": "Reply with exactly OK."}],
        "tools": [{"type": "function", "function": {
            "name": "probe_only", "description": "Do not execute this function.",
            "parameters": {"type": "object", "properties": {}},
        }}],
        "tool_choice": "none",
    }, key, ctx)
    if status == 200 and isinstance(payload, dict):
        return {"status": status, "supported": True, "response": message_text(payload)[:120]}
    return {"status": status, "supported": False, "error": str(payload)[:300]}


def probe_vision(model: str, key: str, ctx: ssl.SSLContext) -> dict:
    image = f"data:image/png;base64,{TINY_PNG}"
    status, payload = request_json({
        "model": model,
        "max_tokens": 32,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Reply with exactly IMAGE."},
            {"type": "image_url", "image_url": {"url": image}},
        ]}],
    }, key, ctx)
    if status == 200 and isinstance(payload, dict):
        return {"status": status, "supported": True, "response": message_text(payload)[:120]}
    return {"status": status, "supported": False, "error": str(payload)[:300]}


def plugin_shortlist(raw_models: list[str]) -> list[str]:
    """Load shortlist logic without requiring a Hermes installation."""
    providers = types.ModuleType("providers")
    providers.register_provider = lambda _profile: None  # type: ignore[attr-defined]
    base = types.ModuleType("providers.base")

    class ProviderProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    base.ProviderProfile = ProviderProfile  # type: ignore[attr-defined]
    sys.modules["providers"] = providers
    sys.modules["providers.base"] = base
    plugin_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(plugin_dir))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_bonzai_probe", plugin_dir / "bonzai" / "__init__.py")
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module._build_smart_shortlist(raw_models)
    finally:
        sys.path.remove(str(plugin_dir))


def catalog_models(key: str, ctx: ssl.SSLContext) -> list[str]:
    request = urllib.request.Request(MODELS_ENDPOINT, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(request, timeout=30, context=ctx) as response:
        data = json.loads(response.read().decode())
    items = data if isinstance(data, list) else data.get("data", [])
    return [item["id"] for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", help="model IDs to probe")
    parser.add_argument("--all", action="store_true", help="probe the plugin shortlist")
    parser.add_argument("--out", type=Path, help="write JSON results to this path")
    args = parser.parse_args()
    if not args.models and not args.all:
        parser.error("provide --models or --all")

    key, ctx = api_key(), ssl_context()
    if args.all:
        models = plugin_shortlist(catalog_models(key, ctx))
    else:
        models = args.models

    results = []
    for model in models:
        print(f"Probing {model}...", flush=True)
        results.append({"model": model, "tools": probe_tools(model, key, ctx), "vision": probe_vision(model, key, ctx)})
    output = {"models": results}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
