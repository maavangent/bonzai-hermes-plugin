#!/usr/bin/env python3
"""Cross-platform installer for the Bonzai Hermes model-provider plugin.

Works on macOS, Linux and Windows. Replaces the bash install.sh / update.sh /
uninstall.sh scripts with a single file that runs anywhere Python 3 is present.

Usage:
    python install.py                # install (default)
    python install.py --update       # git pull (if a checkout) + reinstall
    python install.py --uninstall    # remove plugin, overlay and cache

What it does on install:
    1. Copies the `bonzai/` plugin into ~/.hermes/plugins/model-providers/bonzai/
       (auto-discovered by Hermes — no `plugins enable` needed)
    2. Injects the required HermesOverlay entry into hermes_cli/providers.py so
       `hermes model` / `/model` recognise the provider (without it you get
       "Unknown provider 'bonzai'")
    3. Clears the model cache so the new provider shows up

Honors the HERMES_HOME environment variable; falls back to ~/.hermes.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path resolution (cross-platform — uses pathlib, not bash $HOME expansion)
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
PLUGIN_DIR = HERMES_HOME / "plugins" / "model-providers" / "bonzai"
PROVIDERS_FILE = HERMES_HOME / "hermes-agent" / "hermes_cli" / "providers.py"
CACHE_FILE = HERMES_HOME / "provider_models_cache.json"
SOURCE_PLUGIN = SCRIPT_DIR / "bonzai"

OVERLAY = (
    '    "bonzai": HermesOverlay(\n'
    '        transport="openai_chat",\n'
    '        auth_type="api_key",\n'
    '        base_url_override="https://api-v2.bonzai.iodigital.com/",\n'
    '        extra_env_vars=("BONZAI_API_KEY",),\n'
    "    ),\n"
)

# emoji are pure cosmetics; some Windows consoles (legacy cp1252) choke on
# them, so fall back to ASCII markers when stdout can't encode unicode.
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
# Overlay injection / removal (shared logic, no embedded heredoc Python)
# ---------------------------------------------------------------------------

def add_overlay() -> None:
    if not PROVIDERS_FILE.is_file():
        log(f"{WARN}providers.py not found at {PROVIDERS_FILE}")
        log("   Add the HermesOverlay entry manually (see README).")
        return

    content = PROVIDERS_FILE.read_text(encoding="utf-8")

    if '"bonzai"' in content:
        log(f"{INFO}Overlay for 'bonzai' already present.")
        return

    # Insert just before the closing brace of the HERMES_OVERLAYS dict.
    m = re.search(
        r"(HERMES_OVERLAYS\s*:\s*Dict\[str,\s*HermesOverlay\]\s*=\s*\{)(.*?)(\n\})",
        content,
        re.DOTALL,
    )
    if not m:
        log(f"{WARN}Could not locate HERMES_OVERLAYS dict — add overlay manually (see README).")
        return

    new_block = m.group(1) + m.group(2) + "\n" + OVERLAY + m.group(3)
    new_content = content[: m.start()] + new_block + content[m.end():]

    if new_content == content:
        log(f"{WARN}Overlay insertion produced no change — add manually (see README).")
        return

    PROVIDERS_FILE.write_text(new_content, encoding="utf-8")
    log(f"{OK}HermesOverlay entry added to providers.py")


def remove_overlay() -> None:
    if not PROVIDERS_FILE.is_file():
        log(f"{INFO}providers.py not found; nothing to clean there.")
        return

    content = PROVIDERS_FILE.read_text(encoding="utf-8")
    # Remove the whole "bonzai": HermesOverlay(...), block, including the
    # leading newline, regardless of internal formatting.
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
# Commands
# ---------------------------------------------------------------------------

def do_install() -> None:
    log("Installing Bonzai Hermes plugin...")

    if not SOURCE_PLUGIN.is_dir():
        log(f"{WARN}Source plugin folder not found at {SOURCE_PLUGIN}")
        log("   Run this script from inside the cloned repo.")
        sys.exit(1)

    # 1. Copy plugin files
    if PLUGIN_DIR.exists():
        log("Removing existing installation...")
        shutil.rmtree(PLUGIN_DIR)
    PLUGIN_DIR.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE_PLUGIN, PLUGIN_DIR)
    log(f"{OK}Plugin files installed to {PLUGIN_DIR}")

    # 2. Register overlay
    add_overlay()

    # 3. Clear cache
    clear_cache()

    log("")
    log("Installation complete. Restart Hermes (or 'hermes gateway restart').")
    log("Then run 'hermes model' and select the 'bonzai' provider.")


def do_uninstall() -> None:
    log("Uninstalling Bonzai Hermes plugin...")

    if PLUGIN_DIR.exists():
        shutil.rmtree(PLUGIN_DIR)
        log(f"{OK}Removed {PLUGIN_DIR}")
    else:
        log(f"{INFO}Plugin dir not found (already removed).")

    remove_overlay()
    clear_cache()

    log("")
    log("Uninstall complete. Restart Hermes (or 'hermes gateway restart').")
    log("If 'bonzai' was your active model, switch with 'hermes model' first.")


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
            log(f"{WARN}git pull failed ({exc}); installing local files as-is.")
    else:
        log(f"{INFO}Not a git checkout - installing the files in {SCRIPT_DIR} as-is.")
        log("   For a true update, re-run the one-liner from the README.")

    log("")
    do_install()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install, update or uninstall the Bonzai Hermes plugin.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--update", action="store_true", help="git pull + reinstall")
    group.add_argument("--uninstall", action="store_true", help="remove plugin, overlay and cache")
    args = parser.parse_args()

    if args.uninstall:
        do_uninstall()
    elif args.update:
        do_update()
    else:
        do_install()


if __name__ == "__main__":
    main()
