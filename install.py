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
PROVIDERS_FILE = HERMES_ROOT / "hermes-agent" / "hermes_cli" / "providers.py"
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
    candidates = [
        HERMES_ROOT / "hermes-agent" / "venv" / "bin" / "python3",
        HERMES_ROOT / "hermes-agent" / "venv" / "bin" / "python",
        HERMES_ROOT / "venv" / "bin" / "python3",
        HERMES_ROOT / "venv" / "bin" / "python",
        Path.home() / ".local" / "share" / "hermes-agent" / "venv" / "bin" / "python3",
        HERMES_ROOT / "hermes-agent" / "venv" / "Scripts" / "python.exe",
        HERMES_ROOT / "venv" / "Scripts" / "python.exe",
        Path.home() / "AppData" / "Local" / "hermes-agent" / "venv" / "Scripts" / "python.exe",
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

    class _FallbackYaml:
        @staticmethod
        def safe_load(text: str) -> dict:
            import json
            try:
                return json.loads(text)
            except Exception:
                res: dict = {}
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and ":" in line:
                        k, v = line.split(":", 1)
                        res[k.strip()] = v.strip().strip("\"'")
                return res

        @staticmethod
        def safe_dump(data: dict, handle, **_kwargs) -> None:
            import json
            try:
                handle.write(json.dumps(data, indent=2))
            except Exception:
                for k, v in data.items():
                    handle.write(f"{k}: {v}\n")

    yaml = _FallbackYaml()  # type: ignore


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


def add_overlay() -> None:
    _content, new_content = _overlay_content()

    if new_content is None:
        log(f"{INFO}Overlay for 'bonzai' already present.")
        return

    PROVIDERS_FILE.write_text(new_content, encoding="utf-8")
    log(f"{OK}HermesOverlay entry added to providers.py")


def overlay_missing() -> bool:
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

def _load_config() -> dict:
    if not CONFIG_FILE.is_file():
        return {}
    config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise RuntimeError(f"Hermes config at {CONFIG_FILE} must contain a YAML mapping")
    return config


def _save_config(config: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=CONFIG_FILE.parent, delete=False
    ) as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
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
    """Set or update a variable in ~/.hermes/.env safely."""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    found = False
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith("#") and "=" in stripped:
                k, _ = stripped.split("=", 1)
                if k.strip() == var_name:
                    lines.append(f"{var_name}={value}")
                    found = True
                    continue
            lines.append(line)

    if not found:
        lines.append(f"{var_name}={value}")

    ENV_FILE.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def configure_bonzai_defaults(api_key: str | None = None) -> None:
    """Configure default provider, model, and model_aliases in config.yaml."""
    if api_key:
        set_env_var("BONZAI_API_KEY", api_key)
        log(f"{OK}BONZAI_API_KEY saved to {ENV_FILE}")

    config = _load_config()

    # Configure model defaults
    model_cfg = config.setdefault("model", {})
    if isinstance(model_cfg, dict):
        model_cfg["provider"] = "bonzai"
        model_cfg["base_url"] = "https://api-v2.bonzai.iodigital.com"
        if not model_cfg.get("default"):
            model_cfg["default"] = "gemini-3.7-flash"

    # Configure default aliases
    aliases = config.setdefault("model_aliases", {})
    if isinstance(aliases, dict):
        if "io" not in aliases:
            aliases["io"] = {
                "model": "gemini-3.7-flash",
                "provider": "bonzai",
            }

    _save_config(config)
    log(f"{OK}Bonzai configured as default provider with 'gemini-3.7-flash' in {CONFIG_FILE}")


def add_client_alias(name: str, api_key: str, model: str = "gemini-3.7-flash") -> str:
    """Add a client-specific API key and alias, converting spaces to hyphens."""
    clean_name = re.sub(r"[\s_]+", "-", name.strip().lower())
    clean_name = re.sub(r"[^a-z0-9-]", "", clean_name).strip("-")
    if not clean_name:
        raise ValueError("Invalid alias name. Please use letters, numbers, and hyphens only.")

    env_var = f"BONZAI_{clean_name.upper().replace('-', '_')}_API_KEY"
    set_env_var(env_var, api_key.strip())
    log(f"{OK}{env_var} saved to {ENV_FILE}")

    config = _load_config()
    aliases = config.setdefault("model_aliases", {})
    if not isinstance(aliases, dict):
        aliases = {}
        config["model_aliases"] = aliases

    aliases[clean_name] = {
        "model": model.strip(),
        "provider": "custom",
        "base_url": "https://api-v2.bonzai.iodigital.com",
        "key_env": env_var,
    }
    _save_config(config)
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
                if client_name:
                    model = input("Preferred model for this client [gemini-3.7-flash]: ").strip() or "gemini-3.7-flash"
                    add_client_alias(client_name, existing_key, model)
                    log(f"{OK}Assigned existing key to alias '{client_name.lower()}'.")
                
                log("")
                log("Now, enter your new default iO API key (or press Enter to skip):")
                new_key = input("Paste new default Bonzai API Key: ").strip()
                return new_key if new_key else None
            elif choice == "3":
                pass  # Fall through to prompt
        except (EOFError, KeyboardInterrupt):
            return None

    log("")
    log("👉 Get your Bonzai API key at: https://bonzai.iodigital.com/")
    try:
        key = input("Paste your Bonzai API Key here: ").strip()
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
            key = input(f"Paste the Bonzai API Key for '{name}': ").strip()
        if not key:
            log(f"{WARN}No key provided. Operation cancelled.")
            return
        model = input("Preferred model [gemini-3.7-flash]: ").strip() or "gemini-3.7-flash"
        add_client_alias(name, key, model)
        log("")
        log(f"{OK}Success! In Hermes chat, switch anytime with: /model {name.lower()}")
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

    if not SOURCE_PLUGIN.is_dir() or not SOURCE_KEY_MANAGER.is_dir() or not SOURCE_DESKTOP_PLUGIN.is_file():
        log(f"{WARN}One or more source plugin files are missing from {SCRIPT_DIR}")
        log("   Run this script from inside the repository.")
        sys.exit(1)

    _overlay_content()

    # 1. Cleanly replace any existing old version
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
    log("Bonzai is now ready with 'gemini-3.7-flash' as your default model!")


def do_uninstall() -> None:
    log("Uninstalling Bonzai Hermes plugin...")

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


def do_check() -> int:
    """Diagnose the installation. Returns a process exit code."""
    problems = 0

    if PLUGIN_DIR.is_dir():
        log(f"{OK}Provider installed at {PLUGIN_DIR}")
    else:
        log(f"{WARN}Provider NOT installed (expected {PLUGIN_DIR})")
        problems += 1

    if KEY_MANAGER_DIR.is_dir():
        log(f"{OK}Key Manager backend installed at {KEY_MANAGER_DIR}")
    else:
        log(f"{WARN}Key Manager backend NOT installed (expected {KEY_MANAGER_DIR})")
        problems += 1

    if DESKTOP_PLUGIN_FILE.is_file():
        log(f"{OK}Desktop companion installed at {DESKTOP_PLUGIN_FILE}")
    else:
        log(f"{WARN}Desktop companion NOT installed (expected {DESKTOP_PLUGIN_FILE})")
        problems += 1

    if key_manager_enabled():
        log(f"{OK}{KEY_MANAGER_ID} backend is enabled")
    else:
        log(f"{WARN}{KEY_MANAGER_ID} backend is not enabled or is explicitly disabled")
        problems += 1

    if not PROVIDERS_FILE.is_file():
        log(f"{WARN}Hermes providers.py is missing (expected {PROVIDERS_FILE})")
        problems += 1
    elif overlay_missing():
        log(f"{WARN}HermesOverlay entry is MISSING from providers.py.")
        log("   A `hermes update` most likely replaced the file.")
        log("   Without it /model reports \"Unknown provider 'bonzai'\".")
        problems += 1
    else:
        log(f"{OK}HermesOverlay entry present in providers.py")

    key = get_env_var("BONZAI_API_KEY")
    if key:
        log(f"{OK}BONZAI_API_KEY is configured in {ENV_FILE}")
    else:
        log(f"{WARN}BONZAI_API_KEY is missing from {ENV_FILE}")

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
