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


# Sentinel returned by _classify for models we deliberately hide from the
# picker (non-chat, lightweight tiers, backend/region duplicates), as opposed
# to genuinely unrecognized families (which return family=None).
_DROP = object()


def _classify(model_id: str):
    """Map a model id to (family, version_tuple, canonical_id).

    - family is a string  -> recognized; group it.
    - family is _DROP      -> deliberately hide (non-chat / lightweight / dup).
    - family is None       -> unrecognized family; keep it (future-proof).
    """
    m = model_id

    # Non-chat models — never useful as a chat/agent model.
    if re.search(r"(embedding|rerank|whisper|image|imagen)", m, re.I) or m == "tts":
        return _DROP, None, None

    # Backend/region duplicates and snapshot variants.
    if re.search(r"(-bedrock$|-vertex$|@|^eu\.anthropic\.|^anthropic\.|"
                 r"^uncompliant-global-|-NVFP4$|\d{8})", m, re.I):
        return _DROP, None, None

    # Lightweight tiers — drop from the curated picker.
    if re.search(r"(-mini$|-nano$|-lite$|-bonzai$|-flash-lite$)", m):
        return _DROP, None, None
    if re.match(r"^glm-\d+(?:\.\d+)?-flash$", m):  # GLM flash = lightweight
        return _DROP, None, None

    # --- Claude: two naming schemes, normalized to one canonical id ---
    cm = re.match(r"^claude-(sonnet|opus|haiku)-(\d+)-(\d+)$", m)
    if cm:
        fam, a, b = cm.group(1), int(cm.group(2)), int(cm.group(3))
        return f"claude-{fam}", (a, b), f"claude-{fam}-{a}-{b}"
    cm = re.match(r"^claude-(\d+)-(\d+)-(sonnet|opus|haiku)$", m)
    if cm:
        a, b, fam = int(cm.group(1)), int(cm.group(2)), cm.group(3)
        return f"claude-{fam}", (a, b), f"claude-{fam}-{a}-{b}"
    cm = re.match(r"^claude-(\d+)-(sonnet|opus|haiku)$", m)
    if cm:
        a, fam = int(cm.group(1)), cm.group(2)
        return f"claude-{fam}", (a, 0), f"claude-{fam}-{a}-0"

    # --- OpenAI GPT-5.x / GPT-4 / o-series ---
    g = re.match(r"^gpt-(5(?:\.\d+)?)$", m)
    if g:
        return "gpt-5", (float(g.group(1)),), m
    if m == "gpt-4o":
        return "gpt-4", (4.0,), m
    g = re.match(r"^gpt-(4\.\d+)$", m)
    if g:
        return "gpt-4", (float(g.group(1)),), m
    g = re.match(r"^o(\d+)$", m)
    if g:
        return "o-series", (int(g.group(1)),), m

    # --- Google Gemini (pro / flash, full size only) ---
    g = re.match(r"^gemini-(\d+(?:\.\d+)?)-(pro|flash)$", m)
    if g:
        return f"gemini-{g.group(2)}", (float(g.group(1)),), m

    # --- Zhipu GLM (full size only) ---
    g = re.match(r"^glm-(\d+(?:\.\d+)?)$", m)
    if g:
        return "glm", (float(g.group(1)),), m

    # --- Mistral (Codestral / Devstral) ---
    if m.startswith("codestral"):
        return "mistral-codestral", (0,), m
    if m.startswith("devstral"):
        return "mistral-devstral", (0,), m

    return None, None, None  # unrecognized family — keep it


# Visual separator between the "latest per family" tier and older versions.
# It is not a real model id; selecting it just fails the switch harmlessly.
_SEPARATOR = "──────── oudere versies ────────"

# Display order of families in the top tier.
_FAMILY_ORDER = [
    "claude-opus", "claude-sonnet", "claude-haiku",
    "gpt-5", "gpt-4", "o-series",
    "gemini-pro", "gemini-flash",
    "glm", "mistral-codestral", "mistral-devstral",
]


def _build_smart_shortlist(raw_models: list[str]) -> list[str]:
    """Build a tidy, two-tier shortlist for the model picker.

    Tier 1 (top): the latest model per recognized family.
    Separator.
    Tier 2: older versions of those same families.

    Lightweight tiers, non-chat models (embeddings/tts/image/rerank) and
    backend/region duplicates are dropped entirely. Unknown families are
    NOT dropped — they are appended after tier 2 so new offerings still
    surface (future-proof).
    """
    from collections import defaultdict

    grouped: dict = defaultdict(dict)  # family -> {canonical_id: (version, display_id)}
    unknown: list[str] = []

    for m in raw_models:
        fam, ver, canon = _classify(m)
        if fam is _DROP:
            continue  # deliberately hidden (non-chat / lightweight / dup)
        if fam is None:
            unknown.append(m)  # unrecognized family — keep it (future-proof)
            continue
        # Prefer the canonical spelling (e.g. claude-opus-4-8 over claude-4-8-opus)
        prev = grouped[fam].get(canon)
        if prev is None or m == canon:
            grouped[fam][canon] = (ver, m)

    # Families seen but not in the explicit order list still get shown.
    ordered_families = _FAMILY_ORDER + [f for f in grouped if f not in _FAMILY_ORDER]

    tier1: list[str] = []
    tier2: list[str] = []
    for fam in ordered_families:
        if fam not in grouped:
            continue
        items = sorted(grouped[fam].values(), reverse=True)
        tier1.append(items[0][1])
        tier2.extend(x[1] for x in items[1:])

    result: list[str] = list(tier1)
    if tier2 or unknown:
        result.append(_SEPARATOR)
    result.extend(tier2)
    result.extend(sorted(unknown))

    # Deduplicate while preserving order.
    seen: set = set()
    final: list[str] = []
    for m in result:
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