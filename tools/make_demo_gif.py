"""Record an animated GIF of the overlay for the README.

    .venv\\Scripts\\python.exe tools\\make_demo_gif.py

Uses the real renderer with invented numbers, so the GIF is an honest picture of
the app without publishing anyone's account figures. It never reads or writes
your saved settings and does not touch a running instance.
"""

import ctypes
import ctypes.wintypes as wt
import math
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

OUT = Path(__file__).resolve().parent.parent / "docs" / "demo.gif"
FRAMES = 56
FRAME_MS = 70

now = datetime.now(timezone.utc)
TARGETS = {"session": 64.0, "weekly_all": 38.0, "credits": 24.8}

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

# Drive the animation by hand instead of letting the timer run, so every frame
# is captured in a known state.
ov._stop_animation()
ov.pinned = True
ov.render(demo)
ov._shown_pct.update({k: 0.0 for k in TARGETS})
ov.win.geometry("+140+140")
ov.show()
root.update()
time.sleep(0.4)

hwnd = ov._resolve_hwnd()
user32 = ctypes.WinDLL("user32")
frames = []

for i in range(FRAMES):
    # Bars ease toward their targets, exactly as they do in the real app.
    for key, target in TARGETS.items():
        current = ov._shown_pct.get(key, 0.0)
        ov._shown_pct[key] = current + (target - current) * 0.16

    ov._phase = (ov._phase + 0.45 / 15) % (math.pi * 2)

    # Half way through, flip the padlock so the GIF shows what it does.
    if i == 30:
        ov.pinned = False
        ov._sig = None
    if i == 44:
        ov.pinned = True
        ov._sig = None

    if ov._layout_signature() != ov._sig:
        ov._paint()
    else:
        ov._update_mark()
        ov._update_bars()

    root.update()
    time.sleep(0.012)

    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    frames.append(ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))
                  .convert("RGB"))

ov.hide()
st.stop_event.set()
root.destroy()

# Hold the last frame briefly so the loop does not feel abrupt.
frames.extend([frames[-1]] * 8)

palette = [f.convert("P", palette=1, colors=128) for f in frames]
palette[0].save(OUT, save_all=True, append_images=palette[1:],
                duration=FRAME_MS, loop=0, optimize=True, disposal=2)
print(f"wrote {OUT}  ({len(frames)} frames, {OUT.stat().st_size // 1024} KB)")
