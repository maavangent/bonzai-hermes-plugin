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


# Pure duplicates / non-selectable ids that should never appear in the picker:
#   - backend routes (-bedrock/-vertex), region/vendor prefixes
#     (eu.anthropic.*, anthropic.*), and dated snapshots (@date or -YYYYMMDD)
#   - "uncompliant-global-*" models: these bypass iO's compliance/privacy
#     filtering and must not be offered to colleagues
# All of these are hidden from the shortlist entirely.
_DUPLICATE = re.compile(
    r"(-bedrock$|-vertex$|@|^eu\.anthropic\.|^anthropic\.|\d{8}|^uncompliant-)"
)

# Non-chat model ids that cannot be used as a conversational model and only add
# noise to a model picker: image generation, TTS, speech-to-text, embeddings,
# and rerankers. Matched by substring/prefix and hidden from the shortlist.
_NON_CHAT = re.compile(
    r"(image|embedding|rerank|^tts$|^whisper$|imagen)",
    re.IGNORECASE,
)

# Visual separator between tier 1 (flagships) and tier 2 (everything else).
# Not a real model id — selecting it just fails the switch harmlessly.
_SEPARATOR = "────────────────────────────────"

# Display order of families in tier 1 (newest of each shown up top).
_FAMILY_ORDER = [
    "claude-opus", "claude-sonnet", "claude-haiku",
    "gpt-5", "gpt-4", "o-series",
    "gemini-pro", "gemini-flash",
    "glm", "mistral-codestral", "mistral-devstral",
]


def _claude_identity(m: str):
    """For Claude models, return (identity_key, (major, minor)).

    Bonzai exposes two naming schemes for the same model
    (``claude-opus-4-8`` and ``claude-4-8-opus``). The identity key
    normalizes both so they dedupe; the version drives 'newest wins'.
    Returns (None, None) for non-Claude ids.
    """
    cm = re.match(r"^claude-(sonnet|opus|haiku)-(\d+)-(\d+)$", m)
    if cm:
        return f"claude-{cm.group(1)}-{cm.group(2)}-{cm.group(3)}", (int(cm.group(2)), int(cm.group(3)))
    cm = re.match(r"^claude-(\d+)-(\d+)-(sonnet|opus|haiku)$", m)
    if cm:
        return f"claude-{cm.group(3)}-{cm.group(1)}-{cm.group(2)}", (int(cm.group(1)), int(cm.group(2)))
    cm = re.match(r"^claude-(\d+)-(sonnet|opus|haiku)$", m)
    if cm:
        return f"claude-{cm.group(2)}-{cm.group(1)}", (int(cm.group(1)), 0)
    # claude-sonnet-5 style (family-major, no minor version)
    cm = re.match(r"^claude-(sonnet|opus|haiku)-(\d+)$", m)
    if cm:
        return f"claude-{cm.group(1)}-{cm.group(2)}", (int(cm.group(2)), 0)
    return None, None


def _tier1_family(m: str):
    """Return (family, version) if ``m`` is a flagship chat model eligible for
    tier 1, else (None, None). Lightweight tiers (mini/nano/lite/flash) and
    non-chat models are intentionally NOT flagships — they fall to tier 2.
    """
    key, ver = _claude_identity(m)
    if key:
        return "-".join(key.split("-")[:2]), ver  # claude-opus / -sonnet / -haiku
    if re.match(r"^gpt-5(?:\.\d+)?$", m):
        return "gpt-5", (float(m.split("-")[1]),)
    if m == "gpt-4o":
        return "gpt-4", (4.0,)
    if re.match(r"^gpt-4\.\d+$", m):
        return "gpt-4", (float(m.split("-")[1]),)
    if re.match(r"^o\d+$", m):
        return "o-series", (int(m[1:]),)
    g = re.match(r"^gemini-(\d+(?:\.\d+)?)-(pro|flash)$", m)
    if g:
        return f"gemini-{g.group(2)}", (float(g.group(1)),)
    if re.match(r"^glm-\d+(?:\.\d+)?$", m):
        return "glm", (float(m.split("-")[1]),)
    if m.startswith("codestral"):
        return "mistral-codestral", (0,)
    if m.startswith("devstral"):
        return "mistral-devstral", (0,)
    return None, None


def _build_smart_shortlist(raw_models: list[str]) -> list[str]:
    """Build a two-tier picker list.

    Tier 1: the newest flagship chat model per family (Claude/GPT/Gemini/...).
    Separator line.
    Tier 2: every other selectable chat model — older versions and lightweight
    tiers (mini/nano/flash).

    Hidden entirely: PURE duplicates (backend routes -bedrock/-vertex,
    region/vendor prefixes eu.anthropic.*, dated snapshots), compliance-bypass
    "uncompliant-global-*" models, and non-chat models (image/tts/whisper/
    embeddings/rerank). The two Claude naming schemes are deduped to the
    cleanest spelling. Every id that survives is a real, callable chat model.
    """
    from collections import defaultdict

    # 1. Drop pure duplicates and non-chat models; dedupe Claude naming schemes.
    seen_claude: dict = {}
    kept: list[str] = []
    for m in raw_models:
        if _DUPLICATE.search(m) or _NON_CHAT.search(m):
            continue
        key, _ = _claude_identity(m)
        if key:
            if key in seen_claude:
                # Already have this model; prefer the 'claude-<fam>-<a>-<b>' spelling.
                prev = seen_claude[key]
                if re.match(r"^claude-(sonnet|opus|haiku)-\d", m) and prev != m:
                    kept[kept.index(prev)] = m
                    seen_claude[key] = m
                continue
            seen_claude[key] = m
            kept.append(m)
        else:
            kept.append(m)

    # 2. Tier 1: newest flagship per family, in display order.
    groups: dict = defaultdict(list)
    for m in kept:
        fam, ver = _tier1_family(m)
        if fam:
            groups[fam].append((ver, m))
    tier1: list[str] = [
        sorted(groups[f], reverse=True)[0][1]
        for f in _FAMILY_ORDER if f in groups
    ]

    # 3. Tier 2: everything else, sorted alphabetically.
    tier1_set = set(tier1)
    tier2 = sorted(m for m in kept if m not in tier1_set)

    result = list(tier1)
    if tier2:
        result.append(_SEPARATOR)
        result.extend(tier2)
    return result



class BonzaiProfile(ProviderProfile):
    """Bonzai (api-v2.bonzai.iodigital.com) provider profile."""

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        """Fetch live, build smart shortlist, and cache.

        Returns a list of model IDs on success, or None on failure so the
        caller can fall back to the static _PROVIDER_MODELS list (base class
        contract as of Hermes 0.16+).
        """
        now = time.time()

        if _CACHE["models"] and (now - _CACHE["ts"]) < _CACHE_TTL:
            return _CACHE["models"]

        if not api_key:
            api_key = os.getenv("BONZAI_API_KEY")

        if not api_key:
            logger.warning("Bonzai: no API key available for model fetch")
            return None

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
        # except-block below returns None (caller uses fallback models).
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

        return None


bonzai = BonzaiProfile(
    name="bonzai",
    aliases=("bonzai-api", "io-bonzai", "iodigital"),
    display_name="Bonzai",
    description="Bonzai API provider for iO",
    # Shown in the `hermes model` picker so colleagues know where to get a key.
    signup_url="https://bonzai.iodigital.com/",
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
    # Output-token ceiling per response. Set to 32k — a safe middle ground that
    # is within every Bonzai model's output limit while giving the agent room
    # for large writes (full files, plans, long refactors). The old 8192 cut
    # off long Claude/GPT responses.
    default_max_tokens=32768,
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