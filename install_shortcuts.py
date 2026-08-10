"""Create (or remove) Desktop and Start-menu shortcuts for Claude Vitals.

    python install_shortcuts.py              # create them
    python install_shortcuts.py --uninstall  # remove them

Gives you a normal double-clickable app icon so starting Claude Vitals never
means opening a terminal or an editor. Both shortcuts point at the project's own
venv, so they work regardless of what is on PATH.

This does NOT enable start-at-login -- that stays a separate, explicit choice in
the tray menu.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claude_usage import tray  # noqa: E402

APP_NAME = "Claude Vitals"
PROJECT = Path(__file__).resolve().parent
PYTHONW = PROJECT / ".venv" / "Scripts" / "pythonw.exe"
ENTRY = PROJECT / "run.pyw"
ICON = PROJECT / "docs" / "claude-vitals.ico"


def _desktop_dir():
    """Resolve the real Desktop folder.

    ~/Desktop is wrong whenever OneDrive (or a domain policy) has redirected it,
    so ask the shell for the actual location and only fall back to the naive
    guess if that is unavailable.
    """
    try:
        from win32com.client import Dispatch
        path = Path(Dispatch("WScript.Shell").SpecialFolders("Desktop"))
        if str(path) and path.exists():
            return path
    except Exception:
        pass
    return Path(os.path.expanduser("~")) / "Desktop"


def targets():
    start_menu = Path(os.environ.get("APPDATA", "")) / \
        "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return [_desktop_dir() / f"{APP_NAME}.lnk", start_menu / f"{APP_NAME}.lnk"]


def _write_shortcut(path, app_id):
    """Create a .lnk that carries an explicit AppUserModelID.

    The AppUserModelID is what makes "Pin to taskbar" work. Without it Windows
    sees a shortcut to pythonw.exe -- a generic host it will not pin as its own
    application -- and simply omits the option from the context menu.

    WScript.Shell cannot set that property, so the shortcut is built through
    IShellLink + IPropertyStore directly.
    """
    import pythoncom
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell

    link = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
        shell.IID_IShellLink,
    )
    link.SetPath(str(PYTHONW))
    link.SetArguments(f'"{ENTRY}"')
    link.SetWorkingDirectory(str(PROJECT))
    link.SetIconLocation(str(ICON), 0)
    link.SetDescription("Claude Vitals - Claude usage tray + overlay")

    store = link.QueryInterface(propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(app_id))
    store.Commit()

    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(path), 0)


def create():
    try:
        import pythoncom  # noqa: F401
        from win32com.propsys import propsys  # noqa: F401
    except ImportError:
        print("pywin32 is required. Install with: .venv\\Scripts\\python.exe -m pip install pywin32")
        return 1

    if not PYTHONW.exists():
        print(f"ERROR: {PYTHONW} not found. Create the venv first (see README).")
        return 1

    tray.write_ico(ICON)
    print(f"  icon written -> {ICON}")

    from claude_usage import win32 as w32
    app_id = w32.APP_USER_MODEL_ID

    for path in targets():
        if not path.parent.exists():
            print(f"  skipped (no such folder): {path.parent}")
            continue
        _write_shortcut(path, app_id)
        print(f"  created -> {path}")

    print(f"\n  AppUserModelID: {app_id}")
    print("\nDone. Double-click the Desktop icon, or search 'Claude Vitals' in Start.")
    print("To pin: press Start, type 'Claude Vitals', right-click the result ->")
    print("  Pin to taskbar   (or 'More' -> 'Pin to taskbar' on some builds)")
    print("Note: the RUNNING app has no taskbar button by design -- it lives in")
    print("the system tray. Pinning gives you a launcher, not a window button.")
    return 0


def remove():
    for path in targets():
        if path.exists():
            path.unlink()
            print(f"  removed -> {path}")
        else:
            print(f"  not present: {path}")
    if ICON.exists():
        ICON.unlink()
        print(f"  removed -> {ICON}")
    print("\nShortcuts removed. (Start-with-Windows, if enabled, is separate: "
          "untick it in the tray menu.)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    sys.exit(remove() if args.uninstall else create())
