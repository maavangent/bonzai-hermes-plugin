"""Bonzai API provider for iO

Returns a clean, smart shortlist with only the latest models available through the Bonzai API.
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import time
import urllib.request

from providers import register_provider
from providers.base import ProviderProfile

try:
    from hermes_cli import __version__ as _HERMES_VERSION
except Exception:  # pragma: no cover - defensive
    _HERMES_VERSION = "unknown"

_USER_AGENT = f"HermesAgent/{_HERMES_VERSION}"

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


def _is_noise(model_id: str) -> bool:
    """Filter out redundant / region-specific / date-stamped duplicates."""
    if model_id.startswith("eu.anthropic."):
        return True
    if "@" in model_id:
        return True
    if re.search(r"20\d{6}", model_id):  # date-stamped snapshot duplicates
        return True
    return False


def _build_smart_shortlist(raw_models: list[str]) -> list[str]:
    """Build a clean shortlist.

    Curated, hand-ordered entries (latest Claude per family + key OpenAI
    models) come first so the picker stays tidy. Everything else Bonzai
    exposes is still appended afterwards — so when iO adds new families
    (Gemini, Mistral, new GPT versions, ...) they are NOT silently dropped.
    """
    shortlist: list[str] = []

    # 1. Curated: latest Claude per family (highest version wins)
    for family in ["sonnet", "opus", "haiku"]:
        latest = _get_latest(raw_models, family)
        if latest:
            shortlist.append(latest)

    # 2. Curated: key OpenAI models, in preferred order
    for model in ["gpt-5.5", "gpt-4o", "o3", "o1"]:
        match = next((m for m in raw_models if model in m), None)
        if match:
            shortlist.append(match)

    # 3. Everything else Bonzai offers (future-proof), de-noised + sorted.
    #    Older versions of an already-curated Claude family are dropped too,
    #    so the picker shows only the latest sonnet/opus/haiku — not every
    #    historical point release.
    curated = set(shortlist)

    def _is_superseded_claude(model_id: str) -> bool:
        parsed = _parse_version(model_id)
        if not parsed:
            return False
        family = parsed[0]
        latest = _get_latest(raw_models, family)
        return latest is not None and model_id != latest

    remainder = sorted(
        m for m in raw_models
        if m not in curated
        and not _is_noise(m)
        and not _is_superseded_claude(m)
    )
    shortlist.extend(remainder)

    # Deduplicate while preserving order
    seen: set[str] = set()
    final: list[str] = []
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
        req.add_header("User-Agent", _USER_AGENT)

        # TLS verification stays ON. Bonzai presents a valid, publicly
        # verifiable certificate, but Python on macOS ships its own CA
        # bundle (separate from the system keychain) which can miss the
        # issuer and raise CERTIFICATE_VERIFY_FAILED. Prefer certifi's
        # up-to-date bundle when available; otherwise fall back to the
        # system default. We NEVER disable verification — on failure the
        # except-block below returns the static fallback model list.
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()

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
    # Update to the internal iO key/portal docs URL if there is one — this is
    # shown in the `hermes model` picker so colleagues know where to get a key.
    signup_url="https://www.iodigital.com/",
    base_url="https://api-v2.bonzai.iodigital.com/",
    auth_type="api_key",
    env_vars=("BONZAI_API_KEY",),
    # Consistent attribution on ALL requests (chat + fetch). The base-class
    # client construction picks default_headers up automatically, so iO can
    # identify Hermes traffic in Bonzai logs.
    default_headers={"User-Agent": _USER_AGENT},
    # Cheap/fast model for auxiliary tasks (vision, compression,
    # session-search) so they don't silently fall back to the "auto" backend.
    default_aux_model="claude-haiku-4-5",
    default_max_tokens=8192,
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