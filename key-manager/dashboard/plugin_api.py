"""Secret-safe backend API for the Bonzai Key Manager dashboard."""
from __future__ import annotations

import re
import urllib.error
import urllib.request
import uuid
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from hermes_constants import get_hermes_home

# Importing the provider is necessary when this dashboard plugin is loaded before
# Hermes has discovered model-provider plugins in the current process.
try:  # pragma: no cover - normal installed layout imports it through discovery
    import bonzai  # noqa: F401
except ImportError:  # pragma: no cover - provider may be installed separately
    pass

from agent.credential_pool import (
    AUTH_TYPE_API_KEY,
    STATUS_EXHAUSTED,
    SUPPORTED_POOL_STRATEGIES,
    PooledCredential,
    _exhausted_until,
    get_pool_strategy,
    load_pool,
)
from hermes_cli.auth import (
    PROVIDER_REGISTRY,
    ProviderConfig,
    _auth_store_lock,
    _load_auth_store,
    _save_auth_store,
)
from hermes_cli.config import load_config, save_config
PROVIDER = "bonzai"
CHECK_URL = "https://api-v2.bonzai.iodigital.com/v1/models"
INFERENCE_BASE_URL = "https://api-v2.bonzai.iodigital.com/"
API_KEY_ENV_VAR = "BONZAI_API_KEY"
router = APIRouter()


def _ensure_provider_config() -> None:
    """Ensure env seeding works even when auth loaded before the provider."""
    if PROVIDER in PROVIDER_REGISTRY:
        return
    PROVIDER_REGISTRY[PROVIDER] = ProviderConfig(
        id=PROVIDER,
        name="Bonzai",
        auth_type=AUTH_TYPE_API_KEY,
        inference_base_url=INFERENCE_BASE_URL,
        api_key_env_vars=(API_KEY_ENV_VAR,),
    )


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


class TestCredentialRequest(_NonBlankModel):
    api_key: str = Field(min_length=1, max_length=8192)


class RenameCredentialRequest(_NonBlankModel):
    label: str = Field(min_length=1, max_length=100)


class StrategyRequest(BaseModel):
    strategy: str

    @field_validator("strategy")
    @classmethod
    def supported_strategy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_POOL_STRATEGIES:
            raise ValueError("unsupported credential pool strategy")
        return normalized


def _is_manual(source: str) -> bool:
    normalized = str(source or "").strip().lower()
    return normalized == "manual" or normalized.startswith("manual:")


def _public_credential(entry) -> dict:
    manual = _is_manual(entry.source)
    cooldown_until = _exhausted_until(entry) if entry.last_status == STATUS_EXHAUSTED else None
    # Explicit allow-list: no token-bearing credential object is ever serialized.
    return {
        "id": entry.id,
        "label": entry.label,
        "source": entry.source,
        "auth_type": entry.auth_type,
        "status": entry.last_status or "ok",
        "cooldown_until": cooldown_until,
        "removable": manual,
        "renameable": manual,
    }


def _entry_by_id(pool, credential_id: str):
    entry = next((item for item in pool.entries() if item.id == credential_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return entry


def _manual_entry(pool, credential_id: str):
    entry = _entry_by_id(pool, credential_id)
    if not _is_manual(entry.source):
        raise HTTPException(status_code=403, detail="Only manual credentials can be changed")
    return entry


def key_checker(api_key: str) -> dict:
    """Validate a candidate key without persisting or returning it."""
    request = urllib.request.Request(
        CHECK_URL,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310: fixed HTTPS URL
            response.read(1)
            return {"ok": True, "status": int(response.status)}
    except urllib.error.HTTPError as exc:
        # Never include upstream bodies: they are untrusted and may echo secrets.
        return {"ok": False, "status": int(exc.code), "error": str(exc.reason or "Request failed")}
    except (OSError, urllib.error.URLError):
        return {"ok": False, "status": 0, "error": "Unable to reach Bonzai"}


@router.get("/credentials")
def list_credentials() -> dict:
    _ensure_provider_config()
    pool = load_pool(PROVIDER)
    return {
        "credentials": [_public_credential(entry) for entry in pool.entries()],
        "strategy": get_pool_strategy(PROVIDER),
    }


def _sync_alias_for_label(label: str, api_key: str) -> None:
    """Sync an alias in config.yaml when a credential is added via the UI."""
    slug = re.sub(r"[\s_]+", "-", label.strip().lower())
    slug = re.sub(r"[^a-z0-9-]", "", slug).strip("-")
    if not slug or slug in ("bonzai-api-key", "default", "io"):
        return

    try:
        hermes_home = get_hermes_home()
        env_file = hermes_home / ".env"
        env_var = f"BONZAI_{slug.upper().replace('-', '_')}_API_KEY"

        lines = []
        found = False
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s.startswith("#") and "=" in s:
                    k, _ = s.split("=", 1)
                    if k.strip() == env_var:
                        lines.append(f"{env_var}={api_key.strip()}")
                        found = True
                        continue
                lines.append(line)
        if not found:
            lines.append(f"{env_var}={api_key.strip()}")
        env_file.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

        cfg = load_config()
        aliases = cfg.setdefault("model_aliases", {})
        if isinstance(aliases, dict):
            aliases[slug] = {
                "model": "gemini-3.7-flash",
                "provider": "custom",
                "base_url": INFERENCE_BASE_URL.rstrip("/"),
                "key_env": env_var,
            }
            save_config(cfg)
    except Exception:
        pass


@router.post("/credentials", status_code=201)
def add_credential(request: AddCredentialRequest) -> dict:
    _ensure_provider_config()
    pool = load_pool(PROVIDER)
    entry = pool.add_entry(PooledCredential(
        provider=PROVIDER,
        id=uuid.uuid4().hex[:6],
        label=request.label,
        auth_type=AUTH_TYPE_API_KEY,
        priority=0,
        source="manual",
        access_token=request.api_key,
    ))
    _sync_alias_for_label(request.label, request.api_key)
    return {"credential": _public_credential(entry)}


@router.post("/credentials/test")
def test_credential(request: TestCredentialRequest) -> dict:
    return key_checker(request.api_key)


class TestStoredCredentialRequest(BaseModel):
    id: str = Field(min_length=1, max_length=64)


@router.post("/credentials/test-stored")
def test_stored_credential(request: TestStoredCredentialRequest) -> dict:
    """Test an existing credential without exposing it to the renderer."""
    _ensure_provider_config()
    pool = load_pool(PROVIDER)
    entry = _entry_by_id(pool, request.id.strip())
    api_key = str(getattr(entry, "runtime_api_key", "") or "").strip()
    if not api_key:
        raise HTTPException(status_code=409, detail="Credential has no usable runtime key")
    return key_checker(api_key)


@router.patch("/credentials/{credential_id}")
def rename_credential(credential_id: str, request: RenameCredentialRequest) -> dict:
    _ensure_provider_config()
    pool = load_pool(PROVIDER)
    entry = _manual_entry(pool, credential_id)
    updated = replace(entry, label=request.label)
    pool._replace_entry(entry, updated)
    pool._persist()
    return {"credential": _public_credential(updated)}


@router.delete("/credentials/{credential_id}", status_code=204)
def remove_credential(credential_id: str) -> Response:
    _ensure_provider_config()
    pool = load_pool(PROVIDER)
    _manual_entry(pool, credential_id)
    index = next(i for i, item in enumerate(pool.entries(), start=1) if item.id == credential_id)
    pool.remove_index(index)
    return Response(status_code=204)


@router.post("/credentials/reset")
def reset_cooldowns() -> dict:
    _ensure_provider_config()
    # CredentialPool.reset_statuses() uses the normal concurrency-safe writer,
    # which deliberately preserves a newer on-disk cooldown. An explicit user
    # reset must instead clear those fields atomically in the owning store.
    status_fields = (
        "last_status", "last_status_at", "last_error_code", "last_error_reason",
        "last_error_message", "last_error_reset_at",
    )
    with _auth_store_lock():
        store = _load_auth_store()
        pools = store.get("credential_pool")
        entries = pools.get(PROVIDER, []) if isinstance(pools, dict) else []
        count = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if any(entry.get(field) is not None for field in status_fields):
                for field in status_fields:
                    entry[field] = None
                count += 1
        if count:
            _save_auth_store(store)
    return {"reset": count}


@router.get("/strategy")
def read_strategy() -> dict:
    return {"strategy": get_pool_strategy(PROVIDER)}


@router.put("/strategy")
def write_strategy(request: StrategyRequest) -> dict:
    config = load_config()
    strategies = config.get("credential_pool_strategies")
    if not isinstance(strategies, dict):
        strategies = {}
    strategies[PROVIDER] = request.strategy
    config["credential_pool_strategies"] = strategies
    save_config(config)
    return {"strategy": request.strategy}
