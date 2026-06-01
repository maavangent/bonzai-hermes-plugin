"""Bonzai API provider for iO

Returns a clean, smart shortlist with only the latest models available through the Bonzai API.
"""

import json
import logging
import os
import re
import ssl
import time
import urllib.request
from providers import register_provider
from providers.base import ProviderProfile, _profile_user_agent

logger = logging.getLogger(__name__)

_CACHE: dict = {"models": None, "ts": 0}
_CACHE_TTL = 60


def _parse_version(name: str):
    """Extract (family, major, minor) from clean model names like claude-sonnet-4-6."""
    match = re.search(r"claude-(sonnet|opus|haiku)-(\d+)-(\d+)", name)
    if match:
        family = match.group(1)
        major = int(match.group(2))
        minor = int(match.group(3))
        return (family, major, minor)
    return None


def _get_latest(models: list[str], family: str):
    """Find the model with the highest version number for a family."""
    candidates = []
    for m in models:
        if not m.startswith("claude"):
            continue
        if m.startswith("eu.anthropic."):
            continue
        if "@" in m or re.search(r"20\d{6}", m):
            continue
        parsed = _parse_version(m)
        if parsed and parsed[0] == family:
            candidates.append((parsed, m))

    if not candidates:
        return None

    # Sort by (major, minor) descending
    candidates.sort(key=lambda x: (x[0][1], x[0][2]), reverse=True)
    return candidates[0][1]


def _build_smart_shortlist(raw_models: list[str]) -> list[str]:
    """Build a clean shortlist with the latest Claude models + key GPT/reasoning models."""
    shortlist = []

    # Latest Claude models (highest version number wins)
    for family in ["sonnet", "opus", "haiku"]:
        latest = _get_latest(raw_models, family)
        if latest:
            shortlist.append(latest)

    # Key OpenAI models
    openai_models = ["gpt-5.5", "gpt-4o", "o3", "o1"]
    for model in openai_models:
        if any(model in m for m in raw_models):
            shortlist.append(model)

    # Deduplicate while preserving order
    seen = set()
    final = []
    for m in shortlist:
        if m not in seen:
            seen.add(m)
            final.append(m)

    return final


class BonzaiProfile(ProviderProfile):
    """Bonzai (api-v2.bonzai.iodigital.com) provider profile."""

    def fetch_models(self, *, api_key: str | None = None, timeout: float = 8.0):
        """Fetch live, build smart shortlist, and cache."""
        now = time.time()

        if _CACHE["models"] and (now - _CACHE["ts"]) < _CACHE_TTL:
            return _CACHE["models"]

        if not api_key:
            api_key = os.getenv("BONZAI_API_KEY")

        if not api_key:
            logger.warning("Bonzai: no API key available for model fetch")
            return list(self.fallback_models)

        url = "https://api-v2.bonzai.iodigital.com/v1/models"

        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", _profile_user_agent())

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                data = json.loads(resp.read().decode())

            items = data if isinstance(data, list) else data.get("data", [])
            raw_models = [m["id"] for m in items if isinstance(m, dict) and "id" in m]

            if raw_models:
                shortlist = _build_smart_shortlist(raw_models)
                _CACHE["models"] = shortlist
                _CACHE["ts"] = now
                logger.info("Bonzai: smart shortlist built with %d models", len(shortlist))
                return shortlist

        except Exception as exc:
            logger.warning("Bonzai live model fetch failed: %s", exc)

        return list(self.fallback_models)


bonzai = BonzaiProfile(
    name="bonzai",
    aliases=("bonzai-api", "io-bonzai", "iodigital"),
    display_name="Bonzai",
    description="Bonzai API provider for iO",
    base_url="https://api-v2.bonzai.iodigital.com/",
    auth_type="api_key",
    env_vars=("BONZAI_API_KEY",),
    fallback_models=(
        "claude-sonnet-4-6",
        "claude-opus-4-8",
        "claude-haiku-4-5",
        "gpt-5.5",
        "gpt-4o",
        "o3",
        "o1",
    ),
)

register_provider(bonzai)