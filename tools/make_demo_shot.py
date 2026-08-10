"""Render a demo screenshot of the overlay using invented numbers.

    .venv\\Scripts\\python.exe tools\\make_demo_shot.py

Writes docs/overlay.png. Used for the README and the documentation diagrams so
that no real account figures are published. Builds a throwaway overlay with a
synthetic snapshot; it never reads or writes your saved settings, and it does
not touch a running instance.
"""

import ctypes
import ctypes.wintypes as wt
import sys
import time
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import ImageGrab  # noqa: E402

from claude_usage import overlay as overlay_mod, state as state_mod, usage  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "overlay.png"

now = datetime.now(timezone.utc)
demo = usage.Snapshot(
    limits=[
        usage.Limit(key="session", label="5-hour limit", percent=64.0,
                    resets_at=now + timedelta(hours=2, minutes=35)),
        usage.Limit(key="weekly_all", label="Weekly · all models", percent=38.0,
                    resets_at=now + timedelta(days=3, hours=6)),
    ],
    credits_label="$12.40 / $50.00",
    credits_percent=24.8,
    fetched_at=time.time(),
)

root = tk.Tk()
root.withdraw()
st = state_mod.State()
ov = overlay_mod.Overlay(root, st)

# Fill the bars immediately so the capture is not mid-animation, and put the
# window somewhere predictable without saving that position.
ov.render(demo)
ov._shown_pct.update({"session": 64.0, "weekly_all": 38.0, "credits": 24.8})
ov.win.geometry("+120+120")
ov.show()
root.update()
time.sleep(0.6)
root.update()

hwnd = ov._resolve_hwnd()
rect = wt.RECT()
ctypes.WinDLL("user32").GetWindowRect(hwnd, ctypes.byref(rect))
shot = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))

ov.hide()
st.stop_event.set()
root.destroy()

OUT.parent.mkdir(parents=True, exist_ok=True)
shot.save(OUT)
print(f"wrote {OUT}  ({shot.size[0]}x{shot.size[1]})  — invented numbers, safe to publish")
