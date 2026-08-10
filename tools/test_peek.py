"""Test that an unlocked, buried overlay actually comes to the front.

    .venv\\Scripts\\python.exe tools\\test_peek.py

Reproduces the real failure: with the overlay unlocked, another window covers
it, and "Bring overlay to front" must genuinely raise it. Simply promoting and
demoting the z-order does NOT work -- Windows' foreground lock keeps a
non-foreground window below the active one unless it activates, which we must
never do. So the fix holds it on top briefly instead.

Builds its own overlay off-screen; does not touch a running instance, and backs
up state/ui_state.json.
"""

import ctypes
import ctypes.wintypes as wt
import shutil
import sys
import time
import tkinter as tk
from pathlib import Path

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_usage import config, overlay as overlay_mod, state as state_mod, usage, win32  # noqa: E402

user32 = win32.user32
results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{'  -- ' + detail if detail else ''}")


backup = None
if config.UI_STATE_FILE.exists():
    backup = config.UI_STATE_FILE.with_suffix(".json.peekbak")
    shutil.copy2(config.UI_STATE_FILE, backup)

try:
    root = tk.Tk()
    root.withdraw()
    st = state_mod.State()
    ov = overlay_mod.Overlay(root, st)
    ov.render(usage.from_cache() or usage.Snapshot())
    ov.set_pinned(False)                 # the failing condition: unlocked
    ov.win.geometry("+200+200")
    ov.show()
    root.update()
    time.sleep(0.4)

    hwnd = ov._resolve_hwnd()

    def topmost():
        return bool(win32._get_long(hwnd, win32.GWL_EXSTYLE) & win32.WS_EX_TOPMOST)

    print("=== 1. starts unlocked and not on top ===")
    check("unlocked", ov.pinned is False)
    check("WS_EX_TOPMOST clear", not topmost())

    print("\n=== 2. bring_to_front actually raises it ===")
    fg_before = user32.GetForegroundWindow()
    ov.bring_to_front()
    root.update()
    time.sleep(0.4)
    check("now on top (peek started)", topmost(),
          "this is what was broken -- promote+demote lost to the foreground lock")
    check("still reports as unlocked", ov.pinned is False,
          "a peek must not silently change the user's lock setting")
    check("visible", bool(user32.IsWindowVisible(hwnd)))
    check("focus not taken", user32.GetForegroundWindow() == fg_before)

    print("\n=== 3. peek survives while the user stays put ===")
    for _ in range(4):
        ov.update_peek(fg_before)        # same foreground = user hasn't moved on
        root.update()
        time.sleep(0.3)
    check("still on top after ~1.2s", topmost())

    print("\n=== 4. peek ends when the user switches windows ===")
    time.sleep(PEEK_WAIT := max(0, 1.6 - 1.2))
    ov.update_peek(12345678)             # a different foreground window
    root.update()
    time.sleep(0.3)
    check("dropped back off top", not topmost())
    check("still visible", bool(user32.IsWindowVisible(hwnd)))
    check("lock setting unchanged", ov.pinned is False)

    print("\n=== 5. a switch too soon is ignored (min dwell) ===")
    ov.bring_to_front()
    root.update()
    time.sleep(0.2)
    ov.update_peek(99999999)             # immediate switch, under PEEK_MIN
    check("still on top (change was too early)", topmost(),
          f"min dwell is {overlay_mod.PEEK_MIN_SECONDS}s")
    ov._end_peek()

    print("\n=== 6. locked overlays are unaffected ===")
    ov.set_pinned(True)
    root.update()
    time.sleep(0.3)
    check("locked -> on top", topmost())
    ov.update_peek(4242)
    check("update_peek does not unpin a locked overlay", topmost())
    ov.set_pinned(False)

    st.stop_event.set()
    root.destroy()

finally:
    if backup and backup.exists():
        shutil.copy2(backup, config.UI_STATE_FILE)
        backup.unlink()
        print("\n(restored your ui_state.json)")

print("\n" + ("ALL PASSED" if all(results) else f"{results.count(False)} FAILED"))
sys.exit(0 if all(results) else 1)
