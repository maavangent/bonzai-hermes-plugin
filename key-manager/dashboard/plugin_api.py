"""Secret-safe backend API for the Bonzai Key Manager dashboard.

Client keys are Hermes direct aliases, never Bonzai credential-pool rows.

A pooled key is a rotation candidate: when the default iO key is rate-limited
or rejected, Hermes rotates to the next pool entry, which silently bills iO
work to a client (and the reverse). A client key therefore lives in exactly one
place: an ``.env`` secret plus a ``model_aliases`` entry whose ``key_env``
points at it. Selecting a key is a per-session ``/model <alias>`` switch.
Keys added by older versions as manual pool rows are migrated on first use.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from hermes_constants import get_hermes_home

from hermes_cli.auth import _auth_store_lock, _load_auth_store, _save_auth_store
from hermes_cli.config import load_config, remove_env_value, save_config, save_env_value

PROVIDER = "bonzai"
CHECK_URL = "https://api-v2.bonzai.iodigital.com/v1/models"
BONZAI_BASE_URL = "https://api-v2.bonzai.iodigital.com"
API_KEY_ENV_VAR = "BONZAI_API_KEY"
DEFAULT_SLUG = "io"
DEFAULT_LABEL = "iO (Default)"
DEFAULT_CLIENT_MODEL = "gemini-3.7-flash"
# Names that would shadow the default route or read as the default key.
RESERVED_SLUGS = frozenset({DEFAULT_SLUG, "default", "bonzai", "bonzai-api-key"})
_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SESSION_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,256}")

router = APIRouter()


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

def slugify(label: str) -> str:
    """Alias name for a client label. The installer uses the same rule."""
    slug = re.sub(r"[\s_]+", "-", str(label or "").strip().lower())
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    return re.sub(r"-{2,}", "-", slug).strip("-")


def env_var_for(slug: str) -> str:
    return f"BONZAI_{slug.upper().replace('-', '_')}_API_KEY"


# ---------------------------------------------------------------------------
# Secret-safe reads
# ---------------------------------------------------------------------------

def _read_env_file() -> dict[str, str]:
    """Read this profile's ``.env`` directly.

    Dashboard RPCs can run outside the per-turn secret scope on a multiplexed
    backend, where scope-aware readers fail closed. The file is this profile's
    own secret store, so reading it here is the scoped answer.
    """
    path = get_hermes_home() / ".env"
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _default_key(env: dict[str, str]) -> str:
    # Only the unnumbered default: enumerating BONZAI_API_KEY_2.. is the
    # profile-scoped read that breaks multiplexed dashboard RPCs.
    return (env.get(API_KEY_ENV_VAR) or os.getenv(API_KEY_ENV_VAR, "")).strip()


def _mask(api_key: str) -> str | None:
    if not api_key:
        return None
    return api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "***"


def _is_bonzai_client_alias(entry) -> bool:
    return (
        isinstance(entry, dict)
        and str(entry.get("provider", "")).strip() == "custom"
        and str(entry.get("base_url", "")).strip().rstrip("/") == BONZAI_BASE_URL
        and bool(re.fullmatch(r"BONZAI_[A-Z0-9_]+_API_KEY", str(entry.get("key_env", "")).strip()))
    )


def _aliases(cfg: dict) -> dict:
    aliases = cfg.get("model_aliases")
    if not isinstance(aliases, dict):
        aliases = {}
        cfg["model_aliases"] = aliases
    return aliases


def _client_alias(cfg: dict, slug: str) -> dict:
    entry = _aliases(cfg).get(slug)
    if slug in RESERVED_SLUGS or not _is_bonzai_client_alias(entry):
        raise HTTPException(status_code=404, detail="Client key not found")
    return entry


# ---------------------------------------------------------------------------
# Public (secret-free) views
# ---------------------------------------------------------------------------

def _public_default(cfg: dict, env: dict[str, str]) -> dict:
    alias = _aliases(cfg).get(DEFAULT_SLUG)
    key = _default_key(env)
    return {
        "id": DEFAULT_SLUG,
        "slug": DEFAULT_SLUG,
        "label": DEFAULT_LABEL,
        "kind": "default",
        "model": alias.get("model") if isinstance(alias, dict) else None,
        "masked": _mask(key),
        "configured": bool(key),
        "removable": False,
        "renameable": False,
    }


def _public_client(slug: str, entry: dict, env: dict[str, str]) -> dict:
    # Explicit allow-list: key_env names a secret but is not one.
    key = env.get(str(entry.get("key_env", "")).strip(), "").strip()
    return {
        "id": slug,
        "slug": slug,
        "label": str(entry.get("label") or slug),
        "kind": "client",
        "model": entry.get("model"),
        "masked": _mask(key),
        "configured": bool(key),
        "removable": True,
        "renameable": True,
    }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def _store_secret(env_var: str, api_key: str) -> None:
    """Persist through Hermes' atomic, 0600, scope-aware ``.env`` writer."""
    save_env_value(env_var, api_key)
    if _read_env_file().get(env_var, "").strip() != api_key.strip():
        # save_env_value refuses silently for managed installs/keys.
        raise HTTPException(status_code=409, detail="This Hermes installation does not allow saving that key")


def _alias_entry(label: str, env_var: str, model: str) -> dict:
    return {
        "model": model,
        "provider": "custom",
        "base_url": BONZAI_BASE_URL,
        "key_env": env_var,
        "label": label,
    }


def _is_manual(source) -> bool:
    normalized = str(source or "").strip().lower()
    return normalized == "manual" or normalized.startswith("manual:")


def _legacy_slug(row: dict, aliases: dict) -> str:
    """Alias name for a migrated pool row, never colliding with a foreign alias."""
    slug = slugify(str(row.get("label") or ""))
    suffix = slugify(str(row.get("id") or "")) or "key"
    if not slug or slug in RESERVED_SLUGS:
        slug = f"client-{suffix}"
    existing = aliases.get(slug)
    if existing is not None and not _is_bonzai_client_alias(existing):
        slug = f"{slug}-{suffix}"
    return slug


def migrate_legacy_pool_entries() -> int:
    """Move manual Bonzai pool rows (Key Manager <= 1.x) into aliases.

    Idempotent. An existing alias and ``.env`` value win over the pool copy so
    a key the user edited by hand is never overwritten. The pool rows are only
    dropped after every secret has been written.
    """
    with _auth_store_lock():
        store = _load_auth_store()
        pools = store.get("credential_pool")
        rows = pools.get(PROVIDER) if isinstance(pools, dict) else None
        if not isinstance(rows, list):
            return 0
        manual = [row for row in rows if isinstance(row, dict) and _is_manual(row.get("source"))]
        if not manual:
            return 0

        cfg = load_config()
        aliases = _aliases(cfg)
        env = _read_env_file()
        for row in manual:
            api_key = str(row.get("access_token") or "").strip()
            if not api_key:
                continue
            label = str(row.get("label") or "").strip()
            slug = _legacy_slug(row, aliases)
            existing = aliases.get(slug)
            if _is_bonzai_client_alias(existing):
                env_var = str(existing["key_env"]).strip()
                existing.setdefault("label", label or slug)
            else:
                env_var = env_var_for(slug)
                aliases[slug] = _alias_entry(label or slug, env_var, DEFAULT_CLIENT_MODEL)
            if not env.get(env_var, "").strip():
                _store_secret(env_var, api_key)
        save_config(cfg)

        pools[PROVIDER] = [row for row in rows if not (isinstance(row, dict) and _is_manual(row.get("source")))]
        _save_auth_store(store)
        return len(manual)


# ---------------------------------------------------------------------------
# Routes: keys
# ---------------------------------------------------------------------------

class _NonBlankModel(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def reject_blank(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("must not be blank")
        return value


class AddCredentialRequest(_NonBlankModel):
    label: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=1, max_length=8192)
    model: str | None = Field(default=None, max_length=200)


class TestCredentialRequest(_NonBlankModel):
    api_key: str = Field(min_length=1, max_length=8192)


class TestStoredCredentialRequest(_NonBlankModel):
    id: str = Field(min_length=1, max_length=100)


class RenameCredentialRequest(_NonBlankModel):
    label: str = Field(min_length=1, max_length=100)


def key_checker(api_key: str) -> dict:
    """Validate a candidate key without persisting or returning it."""
    request = urllib.request.Request(
        CHECK_URL,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=10, context=context) as response:  # nosec B310: fixed HTTPS URL
            response.read(1)
            return {"ok": True, "status": int(response.status)}
    except urllib.error.HTTPError as exc:
        # Never include upstream bodies: they are untrusted and may echo secrets.
        return {"ok": False, "status": int(exc.code), "error": str(exc.reason or "Request failed")}
    except (OSError, urllib.error.URLError):
        return {"ok": False, "status": 0, "error": "Unable to reach Bonzai"}


@router.get("/credentials")
def list_credentials() -> dict:
    migrated = migrate_legacy_pool_entries()
    cfg = load_config()
    env = _read_env_file()
    clients = sorted(
        (
            _public_client(slug, entry, env)
            for slug, entry in _aliases(cfg).items()
            if isinstance(slug, str) and slug not in RESERVED_SLUGS and _is_bonzai_client_alias(entry)
        ),
        key=lambda item: item["label"].lower(),
    )
    return {"credentials": [_public_default(cfg, env), *clients], "migrated": migrated}


@router.post("/credentials", status_code=201)
def add_credential(request: AddCredentialRequest) -> dict:
    slug = slugify(request.label)
    if not slug:
        raise HTTPException(status_code=422, detail="Use letters or numbers in the client name")
    if slug in RESERVED_SLUGS:
        raise HTTPException(status_code=422, detail=f"“{request.label}” is reserved for the default iO key")
    cfg = load_config()
    if slug in _aliases(cfg):
        raise HTTPException(status_code=409, detail=f"A key or model alias named “{slug}” already exists")
    env_var = env_var_for(slug)
    _store_secret(env_var, request.api_key)
    _aliases(cfg)[slug] = _alias_entry(request.label, env_var, request.model or DEFAULT_CLIENT_MODEL)
    save_config(cfg)
    return {"credential": _public_client(slug, _aliases(cfg)[slug], _read_env_file())}


@router.post("/credentials/test")
def test_credential(request: TestCredentialRequest) -> dict:
    return key_checker(request.api_key)


@router.post("/credentials/test-stored")
def test_stored_credential(request: TestStoredCredentialRequest) -> dict:
    """Test an existing key server-side without exposing it to the renderer."""
    env = _read_env_file()
    if request.id == DEFAULT_SLUG:
        api_key = _default_key(env)
    else:
        entry = _client_alias(load_config(), request.id)
        api_key = env.get(str(entry["key_env"]).strip(), "").strip()
    if not api_key:
        raise HTTPException(status_code=409, detail="This key has no stored value")
    return key_checker(api_key)


@router.post("/credentials/{slug}/activate")
def activate_credential(slug: str) -> dict:
    """Return the alias to switch to. Kept for Desktop companions <= 1.x."""
    if slug == DEFAULT_SLUG:
        return {"slug": DEFAULT_SLUG, "label": DEFAULT_LABEL}
    entry = _client_alias(load_config(), slug)
    return {"slug": slug, "label": str(entry.get("label") or slug)}


@router.patch("/credentials/{slug}")
def rename_credential(slug: str, request: RenameCredentialRequest) -> dict:
    """Change the display label only. The alias and its secret keep their
    names, so chats already bound to this key stay bound."""
    if slug == DEFAULT_SLUG:
        raise HTTPException(status_code=403, detail="The default iO key cannot be renamed")
    cfg = load_config()
    entry = _client_alias(cfg, slug)
    entry["label"] = request.label
    save_config(cfg)
    return {"credential": _public_client(slug, entry, _read_env_file())}


@router.delete("/credentials/{slug}", status_code=204)
def remove_credential(slug: str) -> Response:
    if slug == DEFAULT_SLUG:
        raise HTTPException(status_code=403, detail="The default iO key cannot be removed here")
    cfg = load_config()
    entry = _client_alias(cfg, slug)
    env_var = str(entry["key_env"]).strip()
    del _aliases(cfg)[slug]
    save_config(cfg)
    still_used = any(
        isinstance(other, dict) and str(other.get("key_env", "")).strip() == env_var
        for other in _aliases(cfg).values()
    )
    if not still_used:
        remove_env_value(env_var)
    _forget_sessions_for(slug)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Routes: per-chat key selection
# ---------------------------------------------------------------------------

def _session_keys_path() -> Path:
    return get_hermes_home() / "bonzai_session_keys.json"


def _session_keys_lock():
    """Cross-process lock for the small session assignment store."""
    try:
        from filelock import FileLock
        return FileLock(str(_session_keys_path()) + ".lock")
    except ImportError:
        from contextlib import nullcontext
        return nullcontext()


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _load_session_keys() -> dict[str, str]:
    path = _session_keys_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        session_id: slug
        for session_id, slug in data.items()
        if isinstance(session_id, str) and isinstance(slug, str)
    }


def _update_session_keys(mutate) -> None:
    with _session_keys_lock():
        data = _load_session_keys()
        mutate(data)
        _atomic_write_json(_session_keys_path(), data)


def _forget_sessions_for(slug: str) -> None:
    def drop(data: dict) -> None:
        for session_id in [sid for sid, value in data.items() if value == slug]:
            del data[session_id]
    _update_session_keys(drop)


def _valid_session_id(session_id: str) -> str:
    session_id = session_id.strip()
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=422, detail="Invalid session id")
    return session_id


class SetSessionKeyRequest(BaseModel):
    slug: str


@router.get("/sessions")
def get_all_session_keys() -> dict:
    return {"sessions": _load_session_keys()}


@router.get("/sessions/{session_id}")
def get_session_key(session_id: str) -> dict:
    session_id = _valid_session_id(session_id)
    return {"session_id": session_id, "slug": _load_session_keys().get(session_id, DEFAULT_SLUG)}


@router.post("/sessions/{session_id}")
def set_session_key(session_id: str, request: SetSessionKeyRequest) -> dict:
    session_id = _valid_session_id(session_id)
    slug = request.slug.strip().lower()
    if len(slug) > 100 or not _SLUG_RE.fullmatch(slug):
        raise HTTPException(status_code=422, detail="Invalid key alias")

    def assign(data: dict) -> None:
        if slug == DEFAULT_SLUG:
            data.pop(session_id, None)
        else:
            data[session_id] = slug
    _update_session_keys(assign)
    return {"session_id": session_id, "slug": slug}
