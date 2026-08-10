"""Test smart visibility: follow-Claude mode hides when Claude loses focus.

    .venv\\Scripts\\python.exe tools\\test_visibility.py

Activates a non-Claude window, checks the overlay hides, then restores Claude
and checks it comes back. Run with the app already running.

This only applies in follow-Claude mode. When *Always visible* is on -- the
default -- staying visible is the correct behaviour, not a failure, so the test
reports SKIP rather than failing. Untick *Always visible* in the tray menu to
exercise the follow-Claude path.
"""

import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_usage import cache, config, win32  # noqa: E402

ALWAYS_VISIBLE = bool(
    cache.load_ui_state().get("always_visible", config.ALWAYS_VISIBLE_DEFAULT)
)

user32 = win32.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

overlay_hwnds, claude_hwnds, other_hwnds = [], [], []


def _pid_name(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = win32.kernel32.OpenProcess(win32.PROCESS_QUERY_LIMITED_INFORMATION,
                                        False, pid.value)
    if not handle:
        return None
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if win32.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            import os
            return os.path.basename(buf.value).lower()
    finally:
        win32.kernel32.CloseHandle(handle)
    return None


def _cb(hwnd, _l):
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    name = _pid_name(hwnd)
    if "TkTopLevel" in cls.value:
        ex = win32._get_long(hwnd, win32.GWL_EXSTYLE)
        if ex & win32.WS_EX_NOACTIVATE:
            overlay_hwnds.append(hwnd)
    elif name == "claude.exe" and user32.IsWindowVisible(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            claude_hwnds.append(hwnd)
    elif name and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 3:
        other_hwnds.append((hwnd, name))
    return True


user32.EnumWindows(EnumWindowsProc(_cb), 0)

if not overlay_hwnds:
    print("FAIL: overlay window not found -- is the app running?")
    sys.exit(1)
overlay = overlay_hwnds[0]
print(f"overlay hwnd={overlay}")
print(f"claude windows: {claude_hwnds[:3]}")
print(f"other candidates: {other_hwnds[:5]}")

if not claude_hwnds or not other_hwnds:
    print("SKIP: need both a Claude window and another app window open.")
    sys.exit(0)


def activate(hwnd):
    """Bring a window to the foreground, working around SetForegroundWindow's
    restrictions by attaching to the current foreground thread first."""
    fg = user32.GetForegroundWindow()
    cur = win32.kernel32.GetCurrentThreadId()
    target_thread = user32.GetWindowThreadProcessId(fg, None)
    user32.AttachThreadInput(cur, target_thread, True)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(cur, target_thread, False)


def poll(label, expect_visible, seconds=3.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        vis = bool(user32.IsWindowVisible(overlay))
        if vis == expect_visible:
            print(f"  PASS  {label}: overlay visible={vis}, "
                  f"foreground={win32.foreground_process_name()!r}")
            return True
        time.sleep(0.25)
    print(f"  FAIL  {label}: overlay visible={bool(user32.IsWindowVisible(overlay))}, "
          f"expected {expect_visible}, foreground={win32.foreground_process_name()!r}")
    return False


results = []

print(f"\nmode: {'ALWAYS VISIBLE' if ALWAYS_VISIBLE else 'FOLLOW CLAUDE'}")

print("\n=== switching to a NON-Claude window ===")
other_hwnd, other_name = other_hwnds[0]
print(f"  activating {other_name} (hwnd={other_hwnd})")
activate(other_hwnd)
time.sleep(1.0)
if ALWAYS_VISIBLE:
    stayed = bool(user32.IsWindowVisible(overlay))
    print(f"  {'PASS' if stayed else 'FAIL'}  always-visible mode: overlay stays up "
          f"(visible={stayed}, foreground={win32.foreground_process_name()!r})")
    results.append(stayed)
    print("  SKIP  follow-Claude hide check -- untick 'Always visible' to test it")
else:
    results.append(poll("overlay hides when Claude loses focus", False))

print("\n=== switching back to Claude ===")
activate(claude_hwnds[0])
time.sleep(1.0)
results.append(poll("overlay returns when Claude regains focus", True))

print("\n=== focus safety during the switch ===")
fg = user32.GetForegroundWindow()
stolen = fg == overlay
print(f"  overlay has focus: {stolen} (must be False)")
results.append(not stolen)

print("\n" + ("ALL PASSED" if all(results) else "SOME CHECKS FAILED"))
sys.exit(0 if all(results) else 1)
