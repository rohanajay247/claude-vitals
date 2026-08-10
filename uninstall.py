"""Remove every trace of Claude Vitals from this machine.

    python uninstall.py            # remove everything outside the project folder
    python uninstall.py --all      # also delete state/ and the virtual environment
    python uninstall.py --dry-run  # show what would be removed, change nothing

Deliberately does NOT touch ~/.claude/.credentials.json — that is your Claude
Code login, not ours. Deleting it would sign you out of Claude Code.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PROJECT = Path(__file__).resolve().parent
HOME = Path.home()
APPDATA = Path(os.environ.get("APPDATA", ""))

APP_NAME = "Claude Vitals"
removed, kept, failed = [], [], []


def desktop_dir():
    """Resolve the real Desktop, which OneDrive often redirects."""
    try:
        from win32com.client import Dispatch
        p = Path(Dispatch("WScript.Shell").SpecialFolders("Desktop"))
        if p.exists():
            return p
    except Exception:
        pass
    return HOME / "Desktop"


def shortcut_targets():
    """Every place a Claude Vitals shortcut can live, including the taskbar pin."""
    return {
        "Desktop shortcut": desktop_dir() / f"{APP_NAME}.lnk",
        "Start menu shortcut": APPDATA / "Microsoft/Windows/Start Menu/Programs" / f"{APP_NAME}.lnk",
        "Start-with-Windows shortcut": APPDATA / "Microsoft/Windows/Start Menu/Programs/Startup" / f"{APP_NAME}.lnk",
        "Taskbar pin": APPDATA / "Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar" / f"{APP_NAME}.lnk",
        "Quick Launch shortcut": APPDATA / "Microsoft/Internet Explorer/Quick Launch" / f"{APP_NAME}.lnk",
    }


def rm(label, path, dry):
    path = Path(path)
    if not path.exists():
        kept.append(f"{label}: not present")
        return
    if dry:
        removed.append(f"WOULD REMOVE  {label}: {path}")
        return
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(f"{label}: {path}")
    except OSError as exc:
        failed.append(f"{label}: {path}  ({exc.strerror})")


def stop_running(dry):
    """Ask any running instance to quit, then confirm it has gone."""
    try:
        from claude_usage import win32
    except Exception:
        return
    lock = win32.acquire_single_instance()
    if lock is None:
        if dry:
            removed.append("WOULD STOP    a running instance")
            return
        print("  An instance is running. Quit it from the tray (right-click -> Quit),")
        print("  then run this again so its files are not locked.")
        sys.exit(1)
    win32.release_single_instance(lock)


def remove_statusline(dry):
    """Delegate to the status line's own uninstaller so settings.json is merged
    rather than clobbered."""
    installer = PROJECT / "statusline" / "install.py"
    target = HOME / ".claude" / "statusline.py"
    settings = HOME / ".claude" / "settings.json"

    has_entry = False
    if settings.exists():
        try:
            has_entry = "statusLine" in json.loads(settings.read_text(encoding="utf-8"))
        except Exception:
            pass

    if not target.exists() and not has_entry:
        kept.append("Status line: not installed")
        return
    if dry:
        removed.append("WOULD REMOVE  status line script and settings.json entry")
        return
    if installer.exists():
        subprocess.run([sys.executable, str(installer), "--uninstall"],
                       capture_output=True)
        removed.append("Status line: script removed, statusLine key cleared "
                       "(your other settings kept)")
    else:
        rm("Status line script", target, dry)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true",
                        help="also delete state/ and .venv inside the project")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would happen, change nothing")
    args = parser.parse_args()
    dry = args.dry_run

    print(f"\n  Claude Vitals — {'DRY RUN' if dry else 'uninstall'}\n  " + "=" * 40)

    stop_running(dry)

    for label, path in shortcut_targets().items():
        rm(label, path, dry)

    remove_statusline(dry)

    # Icon we generated for the shortcuts.
    rm("Shortcut icon", PROJECT / "docs" / "claude-vitals.ico", dry)

    if args.all:
        rm("Saved state (settings, cache, position)", PROJECT / "state", dry)
        rm("Virtual environment", PROJECT / ".venv", dry)

    print("\n  Removed:")
    print("\n".join(f"    {r}" for r in removed) or "    nothing")
    if kept:
        print("\n  Already absent:")
        print("\n".join(f"    {k}" for k in kept))
    if failed:
        print("\n  COULD NOT REMOVE (close the app or Explorer, then retry):")
        print("\n".join(f"    {f}" for f in failed))

    print("\n  NOT touched, on purpose:")
    print(f"    {HOME / '.claude' / '.credentials.json'}")
    print("      ^ your Claude Code login. Removing it would sign you out of Claude Code.")

    if not args.all:
        print("\n  Still inside the project folder: state/ and .venv")
        print("  Use --all to remove those too, or just delete the folder.")

    print(f"\n  Finally, delete the project folder itself:\n    {PROJECT}")
    print("\n  If a taskbar icon lingers, right-click it -> Unpin from taskbar.")
    print("  Windows caches pins until Explorer restarts.\n")


if __name__ == "__main__":
    main()
