"""Test the lock (always-on-top) control end to end.

    .venv\\Scripts\\python.exe tools\\test_lock.py

Builds a real Overlay off-screen, locates the lock button by its canvas tag, and
fires the actual click handler at its centre -- exercising hit-testing,
toggle_pin, set_pinned, the Win32 call and persistence. Does not touch a running
instance and never moves your cursor.

`state/ui_state.json` is backed up and restored, so your saved window position
and pin preference survive the run.
"""

import shutil
import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_usage import cache, config, overlay as overlay_mod, state as state_mod, usage, win32  # noqa: E402

results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{'  -- ' + detail if detail else ''}")


class FakeEvent:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.x_root, self.y_root = x, y


# --- protect the user's saved state ---
backup = None
if config.UI_STATE_FILE.exists():
    backup = config.UI_STATE_FILE.with_suffix(".json.testbak")
    shutil.copy2(config.UI_STATE_FILE, backup)

try:
    root = tk.Tk()
    root.withdraw()

    st = state_mod.State()
    quit_called = []
    refresh_called = []
    ov = overlay_mod.Overlay(root, st,
                             on_quit=lambda: quit_called.append(1),
                             on_refresh=lambda: refresh_called.append(1))

    snap = usage.from_cache() or usage.Snapshot()
    ov.render(snap)
    root.update()

    print(f"overlay built off-screen, pinned={ov.pinned}\n")

    bbox = ov.canvas.bbox("btn_pin")
    check("lock button exists on canvas", bbox is not None, str(bbox))
    if not bbox:
        raise SystemExit(1)

    cx, cy = (bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2
    check("hit-test finds the lock at its centre",
          ov._hit(cx, cy) == "btn_pin", f"got {ov._hit(cx, cy)!r} at ({cx},{cy})")

    start = ov.pinned

    print("\n=== click 1 ===")
    ov._drag_end(FakeEvent(cx, cy))
    root.update()
    time.sleep(0.2)
    check("pin flipped", ov.pinned == (not start), f"{start} -> {ov.pinned}")
    check("persisted to disk", cache.load_ui_state().get("pinned") == ov.pinned,
          f"file={cache.load_ui_state().get('pinned')}")

    print("\n=== click 2: back ===")
    ov._drag_end(FakeEvent(cx, cy))
    root.update()
    time.sleep(0.2)
    check("pin flipped back", ov.pinned == start, f"-> {ov.pinned}")
    check("persisted to disk", cache.load_ui_state().get("pinned") == ov.pinned)

    print("\n=== topmost flag follows the pin, on a shown window ===")
    ov.show()
    root.update()
    time.sleep(0.3)
    hwnd = ov._resolve_hwnd()

    def topmost():
        return bool(win32._get_long(hwnd, win32.GWL_EXSTYLE) & win32.WS_EX_TOPMOST)

    # NOTE: this test process was just launched from the foreground console, so
    # Windows grants it foreground rights when it creates its first window --
    # our window may already be foreground before any action we take. What
    # matters is that an action does not CHANGE who has focus, so sample
    # immediately either side of each action rather than against a baseline
    # captured earlier (which anything on the desktop could have changed since).
    # The real app hands the foreground back at startup; see
    # App._give_back_foreground.
    def without_changing_focus(label, action):
        before = win32.user32.GetForegroundWindow()
        action()
        root.update()
        time.sleep(0.3)
        after = win32.user32.GetForegroundWindow()
        check(label, after == before, f"{before} -> {after}")

    without_changing_focus("locked -> focus unchanged", lambda: ov.set_pinned(True))
    check("locked -> WS_EX_TOPMOST set", topmost())

    without_changing_focus("unlocked -> focus unchanged", lambda: ov.set_pinned(False))
    check("unlocked -> WS_EX_TOPMOST cleared", not topmost())
    check("unlocked -> still visible", bool(win32.user32.IsWindowVisible(hwnd)))

    print("\n=== bring_to_front recovers a buried, unlocked overlay ===")
    ov.state.overlay_enabled = False
    ov.hide()
    root.update()
    without_changing_focus("focus unchanged", ov.bring_to_front)
    check("visible again", bool(win32.user32.IsWindowVisible(hwnd)))
    check("overlay re-enabled", ov.state.overlay_enabled is True)
    # An unlocked overlay is held on top *temporarily* so it can actually
    # surface (Windows' foreground lock defeats a plain raise). What must not
    # change is the user's saved preference. The temporary hold, and its
    # release, are covered by tools/test_peek.py.
    check("lock SETTING unchanged", ov.pinned is False,
          "a peek must not turn into a permanent lock")
    check("peek is active (that is how it surfaces)", topmost())
    ov._end_peek()
    check("releases back off top", not topmost())

    print("\n=== other header buttons still work ===")
    rb = ov.canvas.bbox("btn_refresh")
    ov._drag_end(FakeEvent((rb[0] + rb[2]) // 2, (rb[1] + rb[3]) // 2))
    check("refresh fired", len(refresh_called) == 1)
    xb = ov.canvas.bbox("btn_close")
    ov._drag_end(FakeEvent((xb[0] + xb[2]) // 2, (xb[1] + xb[3]) // 2))
    check("close fired", len(quit_called) == 1)

    st.stop_event.set()
    root.destroy()

finally:
    if backup and backup.exists():
        shutil.copy2(backup, config.UI_STATE_FILE)
        backup.unlink()
        print("\n(restored your saved ui_state.json)")

print("\n" + ("ALL PASSED" if all(results) else f"{results.count(False)} FAILED"))
sys.exit(0 if all(results) else 1)
