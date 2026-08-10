"""Diagnostic: watch which process owns the foreground window.

    .venv\\Scripts\\python.exe tools\\probe_foreground.py [seconds]

Use this if the overlay's smart visibility misbehaves -- it tells you exactly
what process name Windows reports for the Claude desktop app on your machine,
which is what config.CLAUDE_PROCESS_NAMES must contain.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_usage import win32  # noqa: E402

duration = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
print(f"Sampling foreground window for {duration:g}s. Click between windows to test.\n")

seen = {}
steps = int(duration / 0.5)
for i in range(steps):
    name = win32.foreground_process_name()
    seen[name] = seen.get(name, 0) + 1
    print(f"  t={i * 0.5:>4.1f}s  foreground={name!r:<28} is_claude={win32.is_claude_foreground()}")
    time.sleep(0.5)

print("\nsummary:")
for name, count in sorted(seen.items(), key=lambda kv: -kv[1]):
    print(f"  {count:>3}x  {name!r}")
