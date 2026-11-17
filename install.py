#!/usr/bin/env python3
"""Cross-platform installer for the Bonzai Hermes provider and Key Manager.

Works on macOS, Linux and Windows. Replaces manual terminal commands with
a single script or one-click launcher that runs anywhere Python 3 is present.

Usage:
    python install.py                # install (default)
    python install.py --interactive  # interactive wizard (prompts for API key & defaults)
    python install.py --add-alias    # add a client-specific API key alias
    python install.py --update       # git pull (if a checkout) + reinstall
    python install.py --uninstall    # remove plugin, overlay and cache
    python install.py --check        # health check

What it does on install:
    1. Copies the `bonzai/` provider into ~/.hermes/plugins/model-providers/bonzai/
       (auto-discovered by Hermes)
    2. Installs and enables the Key Manager backend, then installs its Desktop
       companion under the active profile's desktop-plugins directory
    3. Injects the required HermesOverlay entry into hermes_cli/providers.py so
       `hermes model` / `/model` recognise the provider
    4. Configures default model, provider, and model_aliases in config.yaml
    5. Clears the model cache so the new provider shows up

Honors the HERMES_HOME environment variable; falls back to ~/.hermes.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import ast
import getpass
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Path resolution (cross-platform — uses pathlib, not bash $HOME expansion)
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def resolve_hermes_root(profile_home: Path) -> Path:
    """Resolve the shared Hermes root independently of a profile-scoped home."""
    if profile_home.parent.name == "profiles":
        return profile_home.parent.parent
    return profile_home


HERMES_ROOT = resolve_hermes_root(HERMES_HOME)
PLUGIN_DIR = HERMES_HOME / "plugins" / "model-providers" / "bonzai"
KEY_MANAGER_ID = "bonzai-key-manager"
KEY_MANAGER_DIR = HERMES_HOME / "plugins" / KEY_MANAGER_ID
DESKTOP_PLUGIN_FILE = HERMES_HOME / "desktop-plugins" / KEY_MANAGER_ID / "plugin.js"
def resolve_providers_file(root: Path) -> Path:
    """Discover source without importing Hermes or loading its profile secrets."""
    conventional = root / "hermes-agent" / "hermes_cli" / "providers.py"
    for candidate in (conventional, Path(sys.prefix).parent / "hermes_cli" / "providers.py"):
        if candidate.is_file():
            return candidate
    try:
        spec = importlib.util.find_spec("hermes_cli")
        for location in (spec.submodule_search_locations or []) if spec else []:
            candidate = Path(location) / "providers.py"
            if candidate.is_file():
                return candidate
    except (ImportError, ValueError, AttributeError):
        pass
    return conventional


PROVIDERS_FILE = resolve_providers_file(HERMES_ROOT)
CACHE_FILE = HERMES_HOME / "provider_models_cache.json"
SOURCE_PLUGIN = SCRIPT_DIR / "bonzai"
SOURCE_KEY_MANAGER = SCRIPT_DIR / "key-manager"
SOURCE_DESKTOP_PLUGIN = SOURCE_KEY_MANAGER / "desktop" / "plugin.js"
CONFIG_FILE = HERMES_HOME / "config.yaml"
ENV_FILE = HERMES_HOME / ".env"

OVERLAY = (
    '    "bonzai": HermesOverlay(\n'
    '        transport="openai_chat",\n'
    '        auth_type="api_key",\n'
    '        base_url_override="https://api-v2.bonzai.iodigital.com/",\n'
    '        extra_env_vars=("BONZAI_API_KEY",),\n'
    "    ),\n"
)


# ---------------------------------------------------------------------------
# Python runtime and PyYAML self-healing
# ---------------------------------------------------------------------------

def _find_hermes_python() -> Path | None:
    """Locate the Python executable inside Hermes's own virtualenv."""
    roots = [
        HERMES_ROOT / "hermes-agent", HERMES_ROOT,
        Path.home() / ".local" / "share" / "hermes-agent",
        Path.home() / "AppData" / "Local" / "hermes-agent",
    ]
    candidates = [
        root / venv / executable
        for root in roots
        for venv in (".venv", "venv")
        for executable in ("bin/python3", "bin/python", "Scripts/python.exe")
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


try:
    import yaml
except ImportError:
    _hermes_py = _find_hermes_python()
    if _hermes_py and Path(sys.executable).resolve() != _hermes_py.resolve():
        try:
            os.execv(str(_hermes_py), [str(_hermes_py)] + sys.argv)
        except Exception:
            pass
    # No PyYAML anywhere: file installation still works, but config.yaml is
    # never parsed or rewritten. A hand-rolled parser would flatten nested
    # sections and write the damage back.
    yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Output styling
# ---------------------------------------------------------------------------

def _supports_unicode() -> bool:
    enc = (sys.stdout.encoding or "").lower()
    return "utf" in enc


_U = _supports_unicode()
OK = "\u2705 " if _U else "[OK] "
INFO = "\u2139\ufe0f  " if _U else "[i] "
WARN = "\u26a0\ufe0f  " if _U else "[!] "


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Overlay injection / removal
# ---------------------------------------------------------------------------

def _overlay_content() -> tuple[str, str | None]:
    """Validate providers.py and return its content plus a patched version."""
    if not PROVIDERS_FILE.is_file():
        raise RuntimeError(
            f"providers.py not found at {PROVIDERS_FILE}; "
            "cannot install the required Bonzai overlay"
        )

    content = PROVIDERS_FILE.read_text(encoding="utf-8")

    if '"bonzai"' in content:
        return content, None

    m = re.search(
        r"(HERMES_OVERLAYS\s*:\s*Dict\[str,\s*HermesOverlay\]\s*=\s*\{)(.*?)(\n\})",
        content,
        re.DOTALL,
    )
    if not m:
        raise RuntimeError(
            "Could not locate HERMES_OVERLAYS dict in providers.py; "
            "refusing to modify an incompatible Hermes source file"
        )

    new_block = m.group(1) + m.group(2) + "\n" + OVERLAY.rstrip("\n") + m.group(3)
    new_content = content[: m.start()] + new_block + content[m.end():]

    if new_content == content:
        raise RuntimeError("Overlay insertion produced no change; refusing to report success")

    return content, new_content


def _native_provider_resolution_supported() -> bool:
    """Return whether this Hermes build resolves registered provider profiles.

    Hermes added the generic ProviderProfile fallback to ``resolve_provider_full``
    in the 0.21 line. On those builds Bonzai must not patch Hermes-owned source
    files: an update can replace that file at any time and the patch is no longer
    needed. Keep the source check deliberately narrow and fail closed for older
    or unusual installations, where the legacy overlay remains the safe fallback.
    """
    try:
        tree = ast.parse(PROVIDERS_FILE.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    resolver = functions.get("resolve_provider_full")
    if resolver is None or "_plugin_profile_pdef" not in functions:
        return False
    # Inspect actual call paths, not comments or an exact upstream return spelling.
    pending = [resolver]
    visited = set()
    while pending:
        function = pending.pop()
        if function.name in visited:
            continue
        visited.add(function.name)
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "_plugin_profile_pdef":
                    return True
                if node.func.id in functions:
                    pending.append(functions[node.func.id])
    return False


def add_overlay() -> None:
    if not PROVIDERS_FILE.is_file():
        log(f"{WARN}Hermes providers.py not found; skipping legacy overlay.")
        return
    if _native_provider_resolution_supported():
        # Remove the legacy patch when upgrading an installation that still has
        # it. This restores Hermes-owned source to the native plugin path and
        # prevents the next Hermes update from looking like a provider failure.
        remove_overlay()
        log(f"{INFO}Hermes natively resolves model-provider plugins; no overlay needed.")
        return

    _content, new_content = _overlay_content()

    if new_content is None:
        log(f"{INFO}Overlay for 'bonzai' already present.")
        return

    PROVIDERS_FILE.write_text(new_content, encoding="utf-8")
    log(f"{OK}HermesOverlay entry added to providers.py")


def overlay_missing() -> bool:
    if _native_provider_resolution_supported():
        return False
    if not PROVIDERS_FILE.is_file():
        return False
    return '"bonzai"' not in PROVIDERS_FILE.read_text(encoding="utf-8")


def remove_overlay() -> None:
    if not PROVIDERS_FILE.is_file():
        log(f"{INFO}providers.py not found; nothing to clean there.")
        return

    content = PROVIDERS_FILE.read_text(encoding="utf-8")
    pattern = r'\n[ \t]*"bonzai":\s*HermesOverlay\((?:[^()]*|\([^()]*\))*\),'
    new_content, n = re.subn(pattern, "", content, count=1)

    if n == 0:
        log(f"{INFO}No 'bonzai' overlay entry found.")
        return

    PROVIDERS_FILE.write_text(new_content, encoding="utf-8")
    log(f"{OK}Removed HermesOverlay entry from providers.py")


def clear_cache() -> None:
    if CACHE_FILE.is_file():
        CACHE_FILE.unlink()
        log(f"{OK}Cleared model cache.")


# ---------------------------------------------------------------------------
# Configuration & .env Helpers
# ---------------------------------------------------------------------------

def _require_yaml() -> None:
    if yaml is None:
        raise RuntimeError(
            "PyYAML is not available, so config.yaml was left untouched. "
            "Run this installer with Hermes' Python "
            "(~/.hermes/hermes-agent/venv/bin/python install.py)."
        )


def _load_config() -> dict:
    _require_yaml()
    if not CONFIG_FILE.is_file():
        return {}
    try:
        config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Hermes config at {CONFIG_FILE} is invalid YAML") from exc
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise RuntimeError(f"Hermes config at {CONFIG_FILE} must contain a YAML mapping")
    for section in ("plugins", "model_aliases"):
        if section in config and not isinstance(config[section], dict):
            raise RuntimeError(f"Hermes config '{section}' value must be a mapping")
    if "model" in config and not isinstance(config["model"], (dict, str)):
        raise RuntimeError("Hermes config 'model' value must be a mapping or model name")
    for field in ("enabled", "disabled"):
        entries = config.get("plugins", {}).get(field, [])
        if not isinstance(entries, list) or not all(isinstance(item, str) for item in entries):
            raise RuntimeError(f"Hermes plugins.{field} must be lists of strings")
    return config


def _hermes_config_writer():
    """Hermes' own comment-preserving config writer, or None when unavailable.

    Only inside Hermes' own venv: importing a Hermes tree into a foreign
    interpreter half-loads it (missing dependencies, other Python version).
    The source tree is derived from the running venv, not from HERMES_HOME,
    because a profile or scratch home need not sit next to the runtime. It
    goes on sys.path because the editable install does not map every
    top-level module (``hermes_yaml``).
    """
    source = Path(sys.prefix).resolve().parent
    if not (source / "hermes_cli" / "config.py").is_file():
        return None
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    try:
        from hermes_cli.config import atomic_config_write
    except Exception:
        return None
    return atomic_config_write


def _save_config(config: dict) -> None:
    _require_yaml()
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    writer = _hermes_config_writer()
    if writer is not None:
        # Keeps the user's comments, key order and quoting intact.
        writer(CONFIG_FILE, config)
        return
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=CONFIG_FILE.parent, delete=False
    ) as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(CONFIG_FILE)


def set_key_manager_enabled(enabled: bool) -> None:
    """Toggle only our backend key while preserving every other plugin entry."""
    config = _load_config()
    plugins = config.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        raise RuntimeError("Hermes config 'plugins' value must be a mapping")
    enabled_plugins = plugins.get("enabled", [])
    disabled_plugins = plugins.get("disabled", [])
    if not isinstance(enabled_plugins, list) or not isinstance(disabled_plugins, list):
        raise RuntimeError("Hermes plugins.enabled and plugins.disabled must be lists")
    enabled_set = set(enabled_plugins)
    disabled_set = set(disabled_plugins)
    if enabled:
        enabled_set.add(KEY_MANAGER_ID)
        disabled_set.discard(KEY_MANAGER_ID)
    else:
        enabled_set.discard(KEY_MANAGER_ID)
        disabled_set.discard(KEY_MANAGER_ID)
    plugins["enabled"] = sorted(enabled_set)
    if "disabled" in plugins or disabled_set:
        plugins["disabled"] = sorted(disabled_set)
    _save_config(config)


def key_manager_enabled() -> bool:
    config = _load_config()
    plugins = config.get("plugins", {})
    if not isinstance(plugins, dict):
        return False
    enabled = plugins.get("enabled", [])
    disabled = plugins.get("disabled", [])
    return (
        isinstance(enabled, list)
        and isinstance(disabled, list)
        and KEY_MANAGER_ID in enabled
        and KEY_MANAGER_ID not in disabled
    )


def get_env_var(var_name: str) -> str | None:
    """Read a variable from ~/.hermes/.env."""
    if not ENV_FILE.is_file():
        return None
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == var_name:
            return v.strip().strip("\"'")
    return None


def set_env_var(var_name: str, value: str) -> None:
    """Set or update a variable in ~/.hermes/.env atomically, owner-only."""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    value = value.replace("\r", "").replace("\n", "")
    lines: list[str] = []
    found = False
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("export "):
                stripped = stripped[len("export "):].lstrip()
            if not stripped.startswith("#") and "=" in stripped:
                k, _ = stripped.split("=", 1)
                if k.strip() == var_name:
                    if not found:
                        lines.append(f"{var_name}={value}")
                    found = True
                    continue
            lines.append(line)

    if not found:
        lines.append(f"{var_name}={value}")

    fd, temporary = tempfile.mkstemp(prefix=".env_", suffix=".tmp", dir=ENV_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).strip() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, ENV_FILE)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def configure_bonzai_defaults(api_key: str | None = None) -> None:
    """Add Bonzai defaults without switching an existing unrelated provider."""
    config = _load_config()
    if api_key:
        set_env_var("BONZAI_API_KEY", api_key)
        log(f"{OK}BONZAI_API_KEY saved to {ENV_FILE}")

    # Only a fresh configuration or an existing Bonzai selection is ours to fill.
    model_cfg = config.setdefault("model", {})
    if isinstance(model_cfg, dict) and (
        model_cfg.get("provider") == "bonzai" or not model_cfg
    ):
        model_cfg["provider"] = "bonzai"
        model_cfg.setdefault("base_url", "https://api-v2.bonzai.iodigital.com")
        if not model_cfg.get("default"):
            model_cfg["default"] = "gpt-6-luna"

    # Configure default aliases
    aliases = config.setdefault("model_aliases", {})
    if isinstance(aliases, dict):
        if "io" not in aliases:
            aliases["io"] = {
                "model": model_cfg.get("default", "gpt-6-luna") if isinstance(model_cfg, dict) and model_cfg.get("provider") == "bonzai" else "gpt-6-luna",
                "provider": "bonzai",
            }

    _save_config(config)
    log(f"{OK}Bonzai alias 'io' configured in {CONFIG_FILE}; existing model selection preserved.")


RESERVED_ALIASES = frozenset({"io", "default", "bonzai", "bonzai-api-key"})


def slugify(name: str) -> str:
    """Alias name for a client label; must match the Key Manager backend."""
    slug = re.sub(r"[\s_]+", "-", name.strip().lower())
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    return re.sub(r"-{2,}", "-", slug).strip("-")


def _env_assignment_exists(var_name: str) -> bool:
    """Include empty/exported assignments when rejecting an orphan collision."""
    if not ENV_FILE.is_file():
        return False
    pattern = rf"^\s*(?:export\s+)?{re.escape(var_name)}\s*="
    return any(re.match(pattern, line) for line in ENV_FILE.read_text(encoding="utf-8").splitlines())


def _restore_installer_file(path: Path, snapshot: tuple[bytes, int] | None) -> None:
    """Restore an installer-owned snapshot atomically, without reparsing secrets."""
    if snapshot is None:
        path.unlink(missing_ok=True)
        return
    content, mode = snapshot
    fd, temporary = tempfile.mkstemp(prefix=".bonzai-rollback-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


@contextmanager
def _installer_config_transaction():
    """Rollback only this installer's exact .env/config targets on write failure."""
    snapshots = {
        path: (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
        for path in (ENV_FILE, CONFIG_FILE)
    }
    try:
        yield
    except BaseException:
        for path, snapshot in snapshots.items():
            _restore_installer_file(path, snapshot)
        raise


def add_client_alias(name: str, api_key: str, model: str = "gemini-3.7-flash") -> str:
    """Add a client-specific API key and alias, converting spaces to hyphens.

    Client keys are aliases, never credential-pool rows, so Hermes can never
    rotate iO work onto a client key after a rate limit.
    """
    clean_name = slugify(name)
    if not clean_name:
        raise ValueError("Invalid alias name. Please use letters, numbers, and hyphens only.")
    if clean_name in RESERVED_ALIASES:
        raise ValueError(f"'{clean_name}' is reserved for the default iO key. Choose a client name.")

    env_var = f"BONZAI_{clean_name.upper().replace('-', '_')}_API_KEY"
    config = _load_config()
    aliases = config.setdefault("model_aliases", {})
    if not isinstance(aliases, dict):
        aliases = {}
        config["model_aliases"] = aliases
    if clean_name in aliases:
        raise ValueError(f"Alias '{clean_name}' already exists. Choose a different name.")
    if _env_assignment_exists(env_var):
        raise ValueError(f"Environment variable '{env_var}' already exists. Choose a different name.")

    # Check collisions before writing the secret so a failed add cannot change
    # an existing key or leave an orphaned environment variable.
    aliases[clean_name] = {
        "model": model.strip(),
        "provider": "custom",
        "base_url": "https://api-v2.bonzai.iodigital.com",
        "key_env": env_var,
        "label": name.strip(),
    }
    with _installer_config_transaction():
        set_env_var(env_var, api_key.strip())
        _save_config(config)
    log(f"{OK}{env_var} saved to {ENV_FILE}")
    log(f"{OK}Client alias '{clean_name}' added to {CONFIG_FILE}")
    log(f"{INFO}Use directly in chat: /model {clean_name}")
    return clean_name


# ---------------------------------------------------------------------------
# Interactive Wizards
# ---------------------------------------------------------------------------

def prompt_api_key_if_needed() -> str | None:
    """Prompt for the Bonzai API key with options to migrate to a client alias."""
    existing_key = get_env_var("BONZAI_API_KEY")
    if existing_key:
        masked = existing_key[:8] + "..." + existing_key[-4:] if len(existing_key) > 12 else "***"
        log(f"{INFO}Existing Bonzai API key found ({masked}).")
        log("  [1] Keep as default iO key (Recommended)")
        log("  [2] Assign this existing key to a specific client/project alias (e.g. landal)")
        log("  [3] Replace with a new key")
        try:
            choice = input("Select an option (1-3) [1]: ").strip() or "1"
            if choice == "1":
                return None
            elif choice == "2":
                client_name = input("Client / project name (e.g. landal, heineken): ").strip()
                if not client_name:
                    return None
                model = input("Preferred model for this client [gemini-3.7-flash]: ").strip() or "gemini-3.7-flash"
                log("A different default iO key is required to move this key to a client.")
                new_key = getpass.getpass("New default Bonzai API Key (Enter cancels the move): ").strip()
                if not new_key or new_key == existing_key:
                    log(f"{WARN}Key move cancelled; no client alias was created.")
                    return None
                try:
                    with _installer_config_transaction():
                        slug = add_client_alias(client_name, existing_key, model)
                        set_env_var("BONZAI_API_KEY", new_key)
                except ValueError as exc:
                    log(f"{WARN}{exc}")
                    return None
                log(f"{OK}Moved existing key to alias '{slug}' and replaced the default key.")
                return new_key
            elif choice == "3":
                pass  # Fall through to prompt
        except (EOFError, KeyboardInterrupt):
            return None

    log("")
    log("👉 Get your Bonzai API key at: https://bonzai.iodigital.com/")
    try:
        key = getpass.getpass("Paste your Bonzai API Key here: ").strip()
        if key:
            return key
    except (EOFError, KeyboardInterrupt):
        pass
    return None


def interactive_add_alias() -> None:
    log("")
    log("====================================================")
    log("  🌿 Add a Client-Specific Bonzai Alias")
    log("====================================================")
    try:
        name = input("Client name (e.g. landal, heineken): ").strip()
        if not name:
            log(f"{WARN}No name provided. Operation cancelled.")
            return

        existing_key = get_env_var("BONZAI_API_KEY")
        key = ""
        if existing_key:
            masked = existing_key[:8] + "..." + existing_key[-4:] if len(existing_key) > 12 else "***"
            use_existing = input(f"Use existing default key ({masked}) for this alias? [y/N]: ").strip().lower()
            if use_existing in ("y", "yes"):
                key = existing_key

        if not key:
            key = getpass.getpass(f"Paste the Bonzai API Key for '{name}': ").strip()
        if not key:
            log(f"{WARN}No key provided. Operation cancelled.")
            return
        model = input("Preferred model [gemini-3.7-flash]: ").strip() or "gemini-3.7-flash"
        slug = add_client_alias(name, key, model)
        log("")
        log(f"{OK}Success! In Hermes chat, switch anytime with: /model {slug}")
    except ValueError as exc:
        log(f"{WARN}{exc}")
    except (EOFError, KeyboardInterrupt):
        log("\nCancelled.")


def interactive_menu() -> None:
    while True:
        log("")
        log("====================================================")
        log("  🌿 iO Bonzai Setup for Hermes")
        log("====================================================")
        log("[1] Install / Update Bonzai (Recommended)")
        log("[2] Add a Client Alias (Multiple API Keys)")
        log("[3] Check Installation Health (--check)")
        log("[4] Uninstall Bonzai (--uninstall)")
        log("[5] Exit")
        log("----------------------------------------------------")
        try:
            choice = input("Select an option (1-5) [1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            log("\nGoodbye!")
            return

        if choice == "1":
            do_install(interactive=True)
            break
        elif choice == "2":
            interactive_add_alias()
        elif choice == "3":
            do_check()
        elif choice == "4":
            do_uninstall()
            break
        elif choice == "5":
            break
        else:
            log(f"{WARN}Invalid choice. Please choose 1-5.")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def do_install(interactive: bool = False) -> None:
    log("Installing Bonzai Hermes plugin...")
    _load_config()  # Fail before replacing any installed files.

    if not SOURCE_PLUGIN.is_dir() or not SOURCE_KEY_MANAGER.is_dir() or not SOURCE_DESKTOP_PLUGIN.is_file():
        log(f"{WARN}One or more source plugin files are missing from {SCRIPT_DIR}")
        log("   Run this script from inside the repository.")
        sys.exit(1)

    if PROVIDERS_FILE.is_file() and not _native_provider_resolution_supported():
        _overlay_content()

    if PLUGIN_DIR.exists():
        log("Existing plugin detected - updating to newest version...")
        shutil.rmtree(PLUGIN_DIR)
    PLUGIN_DIR.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE_PLUGIN, PLUGIN_DIR)
    log(f"{OK}Provider files installed to {PLUGIN_DIR}")

    if KEY_MANAGER_DIR.exists():
        shutil.rmtree(KEY_MANAGER_DIR)
    shutil.copytree(SOURCE_KEY_MANAGER, KEY_MANAGER_DIR, ignore=shutil.ignore_patterns("desktop"))
    DESKTOP_PLUGIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_DESKTOP_PLUGIN, DESKTOP_PLUGIN_FILE)
    set_key_manager_enabled(True)
    log(f"{OK}Key Manager backend installed and enabled at {KEY_MANAGER_DIR}")
    log(f"{OK}Desktop companion installed at {DESKTOP_PLUGIN_FILE}")

    # 2. Register overlay & clear cache
    add_overlay()
    clear_cache()

    # 3. Handle API Key and config defaults
    api_key = None
    if interactive or (sys.stdin.isatty() and not get_env_var("BONZAI_API_KEY")):
        api_key = prompt_api_key_if_needed()

    configure_bonzai_defaults(api_key=api_key)

    log("")
    log("====================================================")
    log(f"{OK}Installation complete!")
    log("====================================================")
    log("Restart Hermes Desktop (or run 'hermes gateway restart').")
    log("Use '/model io' to select Bonzai. Run 'python install.py --check' to verify configuration.")


def do_uninstall() -> None:
    log("Uninstalling Bonzai Hermes plugin...")
    _load_config()  # Fail before removing files if the enablement edit is unsafe.

    if PLUGIN_DIR.exists():
        shutil.rmtree(PLUGIN_DIR)
        log(f"{OK}Removed {PLUGIN_DIR}")
    else:
        log(f"{INFO}Plugin dir not found (already removed).")

    if KEY_MANAGER_DIR.exists():
        shutil.rmtree(KEY_MANAGER_DIR)
        log(f"{OK}Removed {KEY_MANAGER_DIR}")
    if DESKTOP_PLUGIN_FILE.parent.exists():
        shutil.rmtree(DESKTOP_PLUGIN_FILE.parent)
        log(f"{OK}Removed {DESKTOP_PLUGIN_FILE.parent}")
    set_key_manager_enabled(False)

    remove_overlay()
    clear_cache()

    log("")
    log("Uninstall complete. Restart Hermes (or 'hermes gateway restart').")


def do_update() -> None:
    log("Updating Bonzai Hermes plugin...")

    if (SCRIPT_DIR / ".git").is_dir():
        log("Git checkout detected - pulling latest...")
        try:
            subprocess.run(
                ["git", "-C", str(SCRIPT_DIR), "pull", "--ff-only"],
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise RuntimeError(f"git pull failed; update aborted: {exc}") from exc
    else:
        log(f"{INFO}Not a git checkout - installing the files in {SCRIPT_DIR} as-is.")

    log("")
    do_install()


def pooled_client_keys() -> int:
    """Count manual Bonzai credential-pool rows (legacy Key Manager keys)."""
    auth_file = HERMES_HOME / "auth.json"
    if not auth_file.is_file():
        return 0
    try:
        import json
        rows = json.loads(auth_file.read_text(encoding="utf-8")).get("credential_pool", {}).get("bonzai", [])
    except Exception:
        return 0
    return sum(
        1 for row in rows
        if isinstance(row, dict) and str(row.get("source", "")).strip().lower().startswith("manual")
    )


def stale_installed_files() -> list[str]:
    """Installed copies that no longer match this checkout."""
    pairs = [
        (SOURCE_PLUGIN / "__init__.py", PLUGIN_DIR / "__init__.py"),
        (SOURCE_PLUGIN / "plugin.yaml", PLUGIN_DIR / "plugin.yaml"),
        (SOURCE_KEY_MANAGER / "plugin.yaml", KEY_MANAGER_DIR / "plugin.yaml"),
        (SOURCE_KEY_MANAGER / "dashboard" / "plugin_api.py", KEY_MANAGER_DIR / "dashboard" / "plugin_api.py"),
        (SOURCE_DESKTOP_PLUGIN, DESKTOP_PLUGIN_FILE),
    ]
    return [
        str(installed.relative_to(HERMES_HOME))
        for source, installed in pairs
        if source.is_file() and installed.is_file() and source.read_bytes() != installed.read_bytes()
    ]


def _hermes_version_str() -> str:
    """Return the installed Hermes version string, or 'unknown'."""
    try:
        from hermes_cli import __version__
        return str(__version__)
    except Exception:
        return "unknown"


def _hermes_version_ok(version_str: str) -> bool:
    """Return True if the version is >= 0.21.0, or if it cannot be determined."""
    if version_str == "unknown":
        return True  # fail open
    try:
        try:
            from packaging.version import Version
            return Version(version_str) >= Version("0.21.0")
        except ImportError:
            pass
        parts = version_str.strip().split(".")
        major, minor = int(parts[0]), int(parts[1])
        return (major, minor) >= (0, 21)
    except Exception:
        return True  # fail open on parse error


def do_check() -> int:
    """Diagnose the installation. Returns a process exit code."""
    problems = 0

    hermes_version = _hermes_version_str()
    if _hermes_version_ok(hermes_version):
        log(f"{OK}Hermes version: {hermes_version}")
    else:
        log(f"{WARN}Hermes {hermes_version} is too old. This plugin requires Hermes >= 0.21.0 (classify_api_error support). Run 'hermes update'.")
        problems += 1

    if PLUGIN_DIR.is_dir():
        manifest = PLUGIN_DIR / "plugin.yaml"
        try:
            metadata = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        except Exception:
            metadata = None
        if isinstance(metadata, dict) and metadata.get("kind") == "model-provider" and (PLUGIN_DIR / "__init__.py").is_file():
            log(f"{OK}Provider installed at {PLUGIN_DIR}")
        else:
            log(f"{WARN}Provider manifest (kind: model-provider) or __init__.py entrypoint missing/invalid")
            problems += 1
    else:
        log(f"{WARN}Provider NOT installed (expected {PLUGIN_DIR})")
        problems += 1

    if KEY_MANAGER_DIR.is_dir():
        manifest = KEY_MANAGER_DIR / "plugin.yaml"
        if manifest.is_file():
            try:
                kind = yaml.safe_load(manifest.read_text(encoding="utf-8")).get("kind")
            except Exception:
                kind = None
        else:
            kind = None
        if kind == "backend" and (KEY_MANAGER_DIR / "dashboard" / "plugin_api.py").is_file():
            log(f"{OK}Key Manager backend installed at {KEY_MANAGER_DIR}")
        else:
            log(f"{WARN}Key Manager manifest (kind: backend) or dashboard/plugin_api.py entrypoint missing/invalid")
            problems += 1
    else:
        log(f"{WARN}Key Manager backend NOT installed (expected {KEY_MANAGER_DIR})")
        problems += 1

    if DESKTOP_PLUGIN_FILE.is_file():
        log(f"{OK}Desktop companion installed at {DESKTOP_PLUGIN_FILE}")
    else:
        log(f"{WARN}Desktop companion NOT installed (expected {DESKTOP_PLUGIN_FILE})")
        problems += 1

    try:
        backend_enabled = key_manager_enabled()
    except (RuntimeError, OSError) as exc:
        log(f"{WARN}{exc}")
        backend_enabled = False
    if backend_enabled:
        log(f"{OK}{KEY_MANAGER_ID} backend is enabled")
    else:
        log(f"{WARN}{KEY_MANAGER_ID} backend is not enabled or is explicitly disabled")
        problems += 1

    if not PROVIDERS_FILE.is_file():
        log(f"{WARN}Hermes providers.py is missing (expected {PROVIDERS_FILE})")
        problems += 1
    elif _native_provider_resolution_supported():
        log(f"{OK}Hermes natively resolves the Bonzai provider profile (no overlay needed)")
    elif overlay_missing():
        log(f"{WARN}HermesOverlay entry is MISSING from providers.py.")
        log("   A `hermes update` most likely replaced the file.")
        log('   Without it /model reports "Unknown provider \'bonzai\'".')
        problems += 1
    else:
        log(f"{OK}HermesOverlay entry present in providers.py")

    key = get_env_var("BONZAI_API_KEY")
    if key:
        log(f"{OK}BONZAI_API_KEY is configured in {ENV_FILE}")
    else:
        log(f"{WARN}BONZAI_API_KEY is missing from {ENV_FILE}")
        problems += 1

    pooled = pooled_client_keys()
    if pooled:
        log(f"{WARN}{pooled} client key(s) are still in the Bonzai credential pool.")
        log("   Hermes can rotate iO work onto them after a rate limit.")
        log("   Start Hermes Desktop once: the Bonzai Key Manager migrates them automatically.")
        problems += 1
    else:
        log(f"{OK}No client keys in the Bonzai credential pool")

    stale = stale_installed_files()
    if stale:
        log(f"{WARN}Installed files differ from this checkout: {', '.join(stale)}")
        problems += 1

    if problems:
        log("")
        log(f"{INFO}Fix with:  python install.py")
        return 1

    log("")
    log(f"{OK}Bonzai plugin status: everything is healthy and configured correctly!")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install, update, check or configure the Bonzai Hermes plugin.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--interactive", action="store_true", help="start interactive setup wizard")
    group.add_argument("--add-alias", action="store_true", help="add a client-specific API key alias")
    group.add_argument("--update", action="store_true", help="git pull + reinstall")
    group.add_argument("--uninstall", action="store_true", help="remove plugin, overlay and cache")
    group.add_argument("--check", action="store_true", help="diagnose the install")
    args = parser.parse_args()

    if args.uninstall:
        do_uninstall()
    elif args.update:
        do_update()
    elif args.check:
        sys.exit(do_check())
    elif args.add_alias:
        interactive_add_alias()
    elif args.interactive:
        interactive_menu()
    else:
        do_install()


if __name__ == "__main__":
    main()
