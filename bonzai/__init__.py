"""Bonzai API provider for iO.

Builds a clean, ordered picker list from the live Bonzai catalog. See README
("Which models you see") for the selection and ordering rules.
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
_API_KEY_ENV_VAR = "BONZAI_API_KEY"


def _scoped_env(name: str) -> str:
    """Read a secret through Hermes' per-profile scope when it exists.

    ``os.getenv`` would hand one profile another profile's key on a
    multiplexed backend; ``get_secret`` fails closed there instead.
    """
    try:
        from agent.secret_scope import get_secret
    except ModuleNotFoundError as exc:
        if exc.name not in {"agent", "agent.secret_scope"}:
            raise
        return (os.getenv(name) or "").strip()
    return (get_secret(name, "") or "").strip()

logger = logging.getLogger(__name__)

_CACHE: dict = {}  # key -> {"models": [...], "ts": float}; see _cache_key
_CACHE_TTL = 60


def _cache_key(api_key: str) -> str:
    """Scope the in-process cache to one credential and profile.

    One Hermes process can serve several profiles. A module-global list would
    hand profile B the catalog fetched with profile A's key. The digest keeps
    the raw key out of process memory dumps of this dict.
    """
    import hashlib

    home = os.environ.get("HERMES_HOME", "")
    try:
        from hermes_constants import get_hermes_home
        home = str(get_hermes_home())
    except Exception:
        pass
    return hashlib.sha256(f"{home}\0{api_key}".encode()).hexdigest()

# Disk cache filename. The in-process _CACHE dies with the process, so a
# freshly started Hermes with no network would otherwise fall back to a
# hand-written list. See _load_offline_models for why that matters.
_OFFLINE_CACHE_NAME = "bonzai_models_cache.json"


def _offline_cache_path():
    """Path of the last-known-good model list for the active profile."""
    from pathlib import Path

    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home()) / _OFFLINE_CACHE_NAME
    except Exception:
        home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
        return Path(home) / _OFFLINE_CACHE_NAME


def _store_offline_models(models: list) -> None:
    """Persist a successful fetch. Best-effort: never breaks a good fetch."""
    try:
        path = _offline_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"models": list(models), "ts": time.time()}))
    except Exception as exc:  # pragma: no cover - disk/permission edge
        logger.debug("Bonzai: could not persist offline model cache: %s", exc)


def _load_offline_models():
    """Return the last successfully fetched list, or None.

    Preferred over a hardcoded ``fallback_models`` tuple: the file is written
    from the live API, so an offline start still shows the real catalog in the
    order this plugin curated, instead of a snapshot that goes stale silently.
    A missing, unreadable or corrupt file simply yields None.
    """
    try:
        data = json.loads(_offline_cache_path().read_text())
        models = data.get("models")
        if isinstance(models, list) and models:
            return [m for m in models if isinstance(m, str)]
    except Exception:
        return None
    return None


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

# First rows are Bonzai's live, semantic aliases. IDs are checked against the
# live catalog below; targets are never hardcoded because the service may reroute.
_BONZAI_ALIAS_ORDER = [
    "bonzai-executor", "bonzai-analyst", "bonzai-explorer", "bonzai-architect",
]

# GPT generations are listed first. GPT tracks are parsed independently by
# numeric release, then the other supported family order follows.
_FAMILY_ORDER = [
    "gpt-6-luna", "gpt-6-sol", "gpt-6",
    "gpt-5-luna", "gpt-5-sol", "gpt-5-terra", "gpt-5",
    "claude-opus", "claude-sonnet", "claude-haiku",
    "gemini-flash", "gemini-pro",
    "glm", "mistral-codestral", "mistral-devstral",
]

# Number of numeric releases per recognized family retained in the picker.
# Same-release IDs with distinct model tracks remain distinct picker choices.
_MAX_VERSIONS_PER_FAMILY = 3

# Claude ids that spell the version BEFORE the family (claude-3-haiku,
# claude-4-sonnet). The desktop picker derives its label straight from the model
# id, so these render as "3 Haiku" / "4 Sonnet" next to "Haiku 4 5" — the same
# family in two different word orders. We cannot rewrite them: the string we
# return is also the id sent to the API, and `claude-haiku-3` is not a model
# Bonzai serves. So a version-first id is shown ONLY when the API exposes no
# family-first spelling for that same model (dedupe keeps the clean one); when
# it is the only spelling it is dropped rather than shown inconsistently.
_CLAUDE_VERSION_FIRST = re.compile(r"^claude-\d+(?:-\d+)?-(sonnet|opus|haiku)$")

# Suffixes that mark a cheaper/faster derivative rather than a new flagship.
# Versions newer than this stay in a small, sortable same-generation family.
_LIGHTWEIGHT_SUFFIX = re.compile(r"-(mini|nano|lite|flash|fast|small|tiny)$")


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
    """Return a versioned family key for models eligible in the compact picker."""
    key, ver = _claude_identity(m)
    if key:
        return "-".join(key.split("-")[:2]), ver  # claude-opus / -sonnet / -haiku
    if re.match(r"^gpt-6(?:\.\d+)?$", m):
        return "gpt-6", (float(m.split("-")[1]),)
    # Keep named GPT-6 tracks independent: Luna and Sol may publish on
    # different version cadences, so rank versions within each track.
    g = re.match(r"^gpt-(6(?:\.\d+)?)-([a-z][a-z0-9-]*)$", m)
    if g and not _LIGHTWEIGHT_SUFFIX.search(m):
        return f"gpt-6-{g.group(2)}", (float(g.group(1)),)
    if re.match(r"^gpt-5(?:\.\d+)?$", m):
        return "gpt-5", (float(m.split("-")[1]),)
    # Named GPT-5 tracks follow the same per-track release ordering.
    g = re.match(r"^gpt-(5(?:\.\d+)?)-([a-z][a-z0-9-]*)$", m)
    if g and not _LIGHTWEIGHT_SUFFIX.search(m):
        return f"gpt-5-{g.group(2)}", (float(g.group(1)),)
    g = re.match(r"^gpt-(4o|4\.\d+|4)-([a-z][a-z0-9-]*)$", m)
    if g and not _LIGHTWEIGHT_SUFFIX.search(m):
        version = 4.0 if g.group(1) in {"4", "4o"} else float(g.group(1))
        return "gpt-4", (version,)
    if re.match(r"^gpt-4o$", m):
        return "gpt-4", (4.0,)
    if re.match(r"^gpt-4(?:\.\d+)?$", m):
        return "gpt-4", (float(m.split("-")[1]),)
    if m == "gpt-4o-mini":
        return None, None
    if m.startswith("o"):
        return None, None
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
    """Build a compact ordered provider list: aliases, then recent versions."""
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

    # 1b. Any version-first Claude id still standing had no family-first
    #     counterpart to be deduped against, so showing it would put a second
    #     word order ("3 Haiku") next to "Haiku 4 5" in the picker.
    kept = [m for m in kept if not _CLAUDE_VERSION_FIRST.match(m)]

    # 2. Keep each recognized track's three newest releases and all real
    # variants within each release. Track order comes from _FAMILY_ORDER.
    groups: dict = defaultdict(list)
    for m in kept:
        fam, ver = _tier1_family(m)
        if fam:
            groups[fam].append((ver, m))

    buckets_by_track: dict[str, list[list[str]]] = {}
    for family in _FAMILY_ORDER:
        by_version: dict = defaultdict(list)
        for version, model in groups.get(family, []):
            by_version[version].append(model)
        versions = sorted(by_version, reverse=True)[:_MAX_VERSIONS_PER_FAMILY]
        buckets_by_track[family] = [sorted(by_version[version]) for version in versions]

    # Keep Claude's newest release block first. GPT releases sort numerically
    # across the generation tracks; exact ties sort by family name so Luna
    # precedes Sol. IDs remain separate selectable catalog entries.
    claude_families = [family for family in _FAMILY_ORDER if family.startswith("claude-")]
    claude_latest = [
        model
        for family in claude_families
        for model in (buckets_by_track[family][0] if buckets_by_track[family] else [])
    ]
    gpt_families = [family for family in _FAMILY_ORDER if family.startswith("gpt-")]
    gpt_rows: list[tuple[float, str, str]] = []
    for family in gpt_families:
        versions = sorted({version for version, _model in groups.get(family, [])}, reverse=True)
        retained_versions = set(versions[:_MAX_VERSIONS_PER_FAMILY])
        gpt_rows.extend(
            (version[0], family, model)
            for version, model in groups.get(family, [])
            if version in retained_versions
        )
    gpt_rows.sort(key=lambda row: (-row[0], row[1].casefold(), row[2].casefold()))
    gpt_models = [model for _version, _family, model in gpt_rows]

    other_families = [family for family in _FAMILY_ORDER if family not in claude_families and not family.startswith("gpt-")]

    # Keep older Claude releases together after the flagship block. Other
    # families are sorted globally by numeric release. The previous family
    # bucket walk made Gemini 3.7 Flash appear below unrelated models.
    claude_remaining: list[str] = []
    for release_index in range(1, _MAX_VERSIONS_PER_FAMILY):
        for family in claude_families:
            if release_index < len(buckets_by_track[family]):
                claude_remaining.extend(buckets_by_track[family][release_index])

    family_rank = {family: index for index, family in enumerate(other_families)}
    other_rows: list[tuple[float, int, str]] = []
    for family in other_families:
        model_versions = {model: version for version, model in groups[family]}
        for bucket in buckets_by_track[family]:
            for model in bucket:
                version = model_versions[model][0]
                other_rows.append((version, family_rank[family], model))
    other_rows.sort(key=lambda row: (row[1], -row[0], row[2].casefold()))
    other_models = [model for _version, _family_rank, model in other_rows]

    ordered_models = claude_latest + gpt_models + claude_remaining + other_models
    ordered_models = [m for m in ordered_models if not m.startswith(("gpt-4", "o"))]
    aliases = [m for m in _BONZAI_ALIAS_ORDER if m in kept]
    return aliases + ordered_models



# Per-model completion-token ceilings, MEASURED against the live API (a request
# with max_tokens=32768 returns the model's real limit in the 400 body). Only
# models whose ceiling is BELOW default_max_tokens need an entry; everything
# else accepts the generous default. Re-probe after Bonzai adds a backend:
#   python3 tools/probe_max_tokens.py <model> [<model> ...]
_MODEL_MAX_TOKENS: dict = {
    # Bonzai's catalog reports a 16,384 output limit for these models. Keep
    # explicit caps even though the gateway's probe currently accepts 32,768.
    "gpt-4o": 16384,
    "gpt-4o-mini": 16384,
}


def _max_tokens_key(model: str | None) -> str:
    """Normalize a model id for _MODEL_MAX_TOKENS lookup.

    A user can have a date-pinned or backend-routed spelling saved in config
    (``gpt-4o-2024-08-06``, ``gpt-4o-mini-bedrock``) even though the picker
    hides those. They share the upstream model's limit, so strip the suffixes
    the catalog treats as noise before looking the cap up.
    """
    m = (model or "").strip().lower()
    m = re.sub(r"-(bedrock|vertex)$", "", m)
    m = re.sub(r"-\d{8}$", "", m)
    m = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", m)
    return m


def _update_model_capabilities(items: list[dict]) -> None:
    """Import trustworthy limits from Bonzai's catalog into Hermes metadata.

    Bonzai exposes ``max_input_tokens`` and ``max_output_tokens`` on current
    chat entries. Keeping these values on the registered profile lets Hermes
    use them for startup validation and request sizing instead of applying
    generic family guesses. Entries without metadata are left untouched.
    """
    capabilities: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        if item.get("mode") != "chat":
            continue
        model_id = item["id"]
        entry: dict = {}
        context = item.get("max_input_tokens")
        output = item.get("max_output_tokens")
        if isinstance(context, int) and context > 0:
            entry["context_window"] = context
        if isinstance(output, int) and output > 0:
            entry["max_output_tokens"] = output
        if entry:
            capabilities[model_id] = entry
    if capabilities:
        bonzai.model_capabilities.update(capabilities)


def _classify_bonzai_error(
    error,
    *,
    status_code=None,
    error_code=None,
    message="",
    body=None,
    model=None,
):
    """Classify Bonzai gateway failures without exposing credential details.

    Bonzai can relay upstream Vertex/LiteLLM failures as a generic 500. Keep
    those failures in the server-error recovery path instead of treating them
    as a bad local API key. The context is deliberately short and secret-free.
    """
    text = " ".join(
        str(value or "").lower()
        for value in (message, error_code, body, error)
    )
    if status_code in (500, 502) and any(
        marker in text
        for marker in (
            "vertex credentials",
            "jsondecodeerror",
            "unable to load vertex",
            "internal server error",
        )
    ):
        return {
            "reason": "server_error",
            "retryable": True,
            "should_fallback": False,
            "error_context": {
                "provider": "bonzai",
                "upstream_failure": "credential_configuration",
                "model": model,
            },
        }
    return None


class BonzaiProfile(ProviderProfile):
    """Bonzai (api-v2.bonzai.iodigital.com) provider profile."""
    def get_max_tokens(self, model: str | None) -> int | None:
        """Per-model completion-token ceiling, falling back to the default.

        Bonzai fronts several upstream backends with different limits, and it
        does NOT clamp an over-large request — it 400s. Measured against the
        live API: ``max_tokens=32768`` on gpt-4o / gpt-4o-mini returns
        "AzureException BadRequestError - max_tokens is too large: 32768. This
        model supports at most 16384 completion tokens", so every call to those
        models failed outright with the flat 32k default.

        Unknown models keep ``default_max_tokens``: a new model is far more
        likely to support MORE output than less, and capping it on a guess
        would silently truncate long writes.
        """
        cap = _MODEL_MAX_TOKENS.get(_max_tokens_key(model))
        return cap if cap is not None else self.default_max_tokens

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

        if not api_key:
            api_key = _scoped_env(_API_KEY_ENV_VAR)

        if not api_key:
            logger.warning("Bonzai: no API key available for model fetch")
            return None

        cache_key = _cache_key(api_key)
        cached_entry = _CACHE.get(cache_key)
        if cached_entry and (now - cached_entry["ts"]) < _CACHE_TTL:
            return list(cached_entry["models"])

        # Fixed host on purpose: a caller-supplied base_url must never receive
        # the Bonzai key.
        url = self.base_url.rstrip("/") + "/v1/models"

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
                _update_model_capabilities(items)
                _CACHE[cache_key] = {"models": shortlist, "ts": now}
                _store_offline_models(shortlist)
                logger.info("Bonzai: smart shortlist built with %d models", len(shortlist))
                return list(shortlist)

        except Exception as exc:
            logger.warning("Bonzai live model fetch failed: %s", exc)

        cached = _load_offline_models()
        if cached:
            logger.info("Bonzai: using last-known-good model list (%d models)", len(cached))
            return cached
        return None


def _profile_supports_field(field_name: str) -> bool:
    """Return True when ProviderProfile's dataclass definition includes ``field_name``.

    Hermes added ``classify_api_error`` (and similar optional kwargs) gradually.
    On builds older than ~0.21 the field is absent from the dataclass, and passing
    it as a keyword argument raises TypeError at import time — breaking the whole
    plugin load. Checking the dataclass fields first lets the plugin degrade
    gracefully: the capability is skipped on old builds instead of crashing.
    """
    import dataclasses
    try:
        return any(f.name == field_name for f in dataclasses.fields(ProviderProfile))
    except TypeError:
        # ProviderProfile is not a dataclass (e.g. a test stub). Fall back to
        # checking class annotations, then hasattr on a dummy instance.
        annotations = getattr(ProviderProfile, "__annotations__", {})
        if field_name in annotations:
            return True
        try:
            return hasattr(ProviderProfile(name="_probe"), field_name)
        except Exception:
            return False


_PROFILE_KWARGS: dict = dict(
    name="bonzai",
    aliases=("bonzai-api", "io-bonzai", "iodigital"),
    display_name="Bonzai",
    description="Bonzai API provider for iO",
    # Shown in the `hermes model` picker so colleagues know where to get a key.
    signup_url="https://bonzai.iodigital.com/",
    base_url="https://api-v2.bonzai.iodigital.com/",
    auth_type="api_key",
    env_vars=(_API_KEY_ENV_VAR,),
    # Consistent attribution on ALL requests (chat + fetch). The base-class
    # client construction picks default_headers up automatically, so iO can
    # identify Hermes traffic in Bonzai logs.
    default_headers={"User-Agent": _USER_AGENT},
    # Cheap/fast model for auxiliary tasks (vision, compression,
    # session-search) so they don't silently fall back to the "auto" backend.
    default_aux_model="claude-haiku-4-5",  # Re-probe after each Claude Haiku release
    # Output-token ceiling per response. Set to 32k — a safe middle ground that
    # is within every Bonzai model's output limit while giving the agent room
    # for large writes (full files, plans, long refactors). The old 8192 cut
    # off long Claude/GPT responses.
    default_max_tokens=32768,
    # Bonzai's OpenAI-compatible gateway accepted a harmless image probe for
    # all 40 current shortlist models. Vision is therefore a provider-wide
    # capability; per-model context/output limits still come from the catalog.
    supports_vision=True,
    supports_vision_tool_messages=True,
    model_capabilities={
        "gemini-3.7-flash": {"context_window": 1_048_576},
    },
)

# classify_api_error was added to ProviderProfile in Hermes ~0.21. Guard the kwarg
# so the plugin loads cleanly on older builds (without error classification) instead
# of crashing at import time with "unexpected keyword argument 'classify_api_error'".
if _profile_supports_field("classify_api_error"):
    _PROFILE_KWARGS["classify_api_error"] = _classify_bonzai_error
else:
    logger.warning(
        "Bonzai: classify_api_error is not supported by this Hermes build. "
        "Run 'hermes update' to enable Bonzai-specific error classification."
    )

bonzai = BonzaiProfile(
    **_PROFILE_KWARGS,
    # Deliberately EMPTY. Hermes merges fallback_models AHEAD of the live list
    # (hermes_cli/models.py::provider_model_ids), so any hand-written tuple here
    # pins a stale order to the top of the picker and buries newly released
    # flagships — claude-sonnet-4-6 outranked claude-opus-5 for exactly this
    # reason. Offline resilience is handled by the disk cache written from real
    # fetches (_store_offline_models) instead of a snapshot that rots silently.
    fallback_models=(),
)

register_provider(bonzai)