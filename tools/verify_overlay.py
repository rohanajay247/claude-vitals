"""Verify the running overlay: existence, style flags, visibility, focus safety.

    .venv\\Scripts\\python.exe tools\\verify_overlay.py

Checks the guarantee that matters: while the overlay is visible and topmost, the
foreground window must still be Claude, not us.
"""

import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

# MUST come before any window query or screen grab. The app itself is
# per-monitor DPI aware; if this checker is not, Windows virtualises every
# coordinate we read (a 340px window reports as 227 at 150% scaling) and
# ImageGrab then captures the wrong region entirely.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import ImageGrab  # noqa: E402

from claude_usage import config, win32  # noqa: E402

user32 = win32.user32

EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
found = []


def _cb(hwnd, _lparam):
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)

    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    # Tk's top-level window class on Windows. The app owns two of these -- the
    # withdrawn root and the overlay -- so identify the overlay by its
    # WS_EX_NOACTIVATE style rather than by enumeration order, which varies.
    if "TkTopLevel" in cls.value:
        ex = win32._get_long(hwnd, win32.GWL_EXSTYLE)
        is_overlay = bool(ex & win32.WS_EX_NOACTIVATE)
        found.append((hwnd, buf.value, cls.value, pid.value, is_overlay))
    return True


user32.EnumWindows(EnumWindowsProc(_cb), 0)

print("=== 1. locate overlay window ===")
if not found:
    print("   NO Tk top-level window found -- is the app running?")
    sys.exit(1)

for hwnd, title, cls, pid, is_overlay in found:
    role = "OVERLAY" if is_overlay else "root (withdrawn)"
    print(f"   hwnd={hwnd} class={cls!r} pid={pid}  -> {role}")

overlays = [row for row in found if row[4]]
if not overlays:
    print("   FAIL: none of the Tk windows carry WS_EX_NOACTIVATE")
    sys.exit(1)
hwnd = overlays[0][0]
print(f"   using overlay hwnd={hwnd}")

print("\n=== 2. extended style flags ===")
ex = win32._get_long(hwnd, win32.GWL_EXSTYLE)
checks = {
    "WS_EX_NOACTIVATE (no focus theft)": win32.WS_EX_NOACTIVATE,
    "WS_EX_TOOLWINDOW (not in Alt-Tab)": win32.WS_EX_TOOLWINDOW,
    "WS_EX_TOPMOST   (locked on top)":  win32.WS_EX_TOPMOST,
}
for name, flag in checks.items():
    print(f"   {'SET  ' if ex & flag else 'UNSET'}  {name}")
if not (ex & win32.WS_EX_TOPMOST):
    print("   (TOPMOST unset is expected when the overlay is UNLOCKED)")

print("\n=== 3. geometry / visibility ===")
rect = wt.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
visible = bool(user32.IsWindowVisible(hwnd))
print(f"   visible={visible}  rect=({rect.left},{rect.top})-({rect.right},{rect.bottom})"
      f"  size={rect.right - rect.left}x{rect.bottom - rect.top}")

print("\n=== 4. FOCUS SAFETY: foreground must stay Claude ===")
for i in range(6):
    fg_name = win32.foreground_process_name()
    fg_hwnd = user32.GetForegroundWindow()
    vis = bool(user32.IsWindowVisible(hwnd))
    stolen = fg_hwnd == hwnd
    print(f"   t={i * 0.5:>3.1f}s  overlay_visible={vis!s:<5} foreground={fg_name!r:<16}"
          f" overlay_has_focus={stolen}")
    if stolen:
        print("   *** FOCUS STOLEN -- this is a failure ***")
    time.sleep(0.5)

print("\n=== 5. screenshot of overlay region ===")
if visible and rect.right > rect.left:
    pad = 8
    shot = ImageGrab.grab((max(0, rect.left - pad), max(0, rect.top - pad),
                           rect.right + pad, rect.bottom + pad))
    out = config.STATE_DIR / "overlay_shot.png"
    shot.save(out)
    print(f"   saved -> {out}  ({shot.size[0]}x{shot.size[1]})")
else:
    print("   overlay not visible right now (is the Claude app in the foreground?)")
