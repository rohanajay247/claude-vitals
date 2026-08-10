#!/usr/bin/env python3
"""Install / uninstall the Claude Code status line.

    python statusline/install.py            # install
    python statusline/install.py --uninstall

Copies statusline.py to ~/.claude/statusline.py and registers it in
~/.claude/settings.json under "statusLine".

WINDOWS GOTCHA
--------------
The command string is written with FORWARD SLASHES. Claude Code runs the status
line through Git Bash on Windows, and Git Bash treats backslashes as escape
characters -- `C:\\Users\\...` silently becomes `C:Users...`, the file is not
found, and the status line just never appears with no error anywhere. Forward
slashes work fine on Windows for both Python and the shell.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
SETTINGS = CLAUDE_DIR / "settings.json"
TARGET = CLAUDE_DIR / "statusline.py"
SOURCE = Path(__file__).with_name("statusline.py")


def posixish(path):
    """Absolute path with forward slashes, quoted only if it needs to be."""
    text = str(Path(path).resolve()).replace("\\", "/")
    return f'"{text}"' if " " in text else text


def load_settings():
    """Read settings.json, tolerating absence. A corrupt file is fatal on
    purpose -- silently discarding the user's other settings would be worse."""
    if not SETTINGS.exists():
        return {}
    raw = SETTINGS.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: {SETTINGS} is not valid JSON ({exc}).")
        print("Fix or move it, then re-run. Refusing to overwrite it.")
        sys.exit(1)
    return data if isinstance(data, dict) else {}


def save_settings(data):
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    if SETTINGS.exists():
        backup = SETTINGS.with_suffix(".json.bak")
        shutil.copy2(SETTINGS, backup)
        print(f"  backed up existing settings -> {backup}")
    SETTINGS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def install():
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, TARGET)
    print(f"  copied {SOURCE.name} -> {TARGET}")

    command = f"{posixish(sys.executable)} {posixish(TARGET)}"

    settings = load_settings()
    existing = settings.get("statusLine")
    if isinstance(existing, dict) and existing.get("command") not in (None, command):
        print(f"  NOTE: replacing existing statusLine command: {existing.get('command')}")

    # Merge: touch only the statusLine key, leave every other setting alone.
    settings["statusLine"] = {"type": "command", "command": command}
    save_settings(settings)

    print(f"  registered statusLine in {SETTINGS}")
    print(f"  command: {command}")
    print("\nDone. Restart Claude Code (or start a new session) to see it.")


def uninstall():
    settings = load_settings()
    if settings.pop("statusLine", None) is not None:
        save_settings(settings)
        print(f"  removed statusLine from {SETTINGS}")
    else:
        print("  no statusLine entry in settings.json")

    if TARGET.exists():
        TARGET.unlink()
        print(f"  deleted {TARGET}")
    else:
        print(f"  {TARGET} not present")

    print("\nUninstalled.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    uninstall() if args.uninstall else install()
