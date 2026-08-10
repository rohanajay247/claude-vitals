"""Verify only one Claude Vitals can run at a time.

    .venv\\Scripts\\python.exe tools\\test_single_instance.py

Launches the app twice for real and checks the second exits instead of adding a
second tray icon and a second poll loop. Also checks the lock is released when
the process ends, so a crash can never leave the app unstartable.
"""

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claude_usage import win32  # noqa: E402

PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
ENTRY = ROOT / "run.pyw"

user32 = win32.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{'  -- ' + detail if detail else ''}")


def tray_windows():
    """PIDs owning a tray window -- one distinct PID per running instance.

    Searched system-wide rather than under the PID we launched: on Windows a
    venv's pythonw.exe is a launcher stub that re-execs the base interpreter, so
    the process actually owning the windows has a different PID entirely.
    """
    found = []

    def cb(hwnd, _l):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if "claude-vitals" in cls.value.lower():
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found.append(pid.value)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return set(found)


def wait_for_trays(count, timeout=45):
    """Wait for exactly `count` instances to be showing a tray icon.

    A cold start under pythonw.exe can take ~20s (bytecode compilation plus
    pystray setting up its message loop), so this polls rather than sleeping a
    fixed amount -- a fixed sleep made this test fail for the wrong reason.
    """
    deadline = time.time() + timeout
    pids = tray_windows()
    while time.time() < deadline:
        pids = tray_windows()
        if len(pids) == count:
            return pids
        time.sleep(1.0)
    return pids


def kill_app():
    """Kill the process that actually owns the windows, not the launcher stub."""
    for pid in tray_windows():
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    time.sleep(2.0)


print("=== 0. lock is free before we start ===")
lock = win32.acquire_single_instance()
check("no instance holds the lock", lock is not None,
      "quit any running copy first" if lock is None else "")
if lock is None:
    sys.exit(1)
win32.release_single_instance(lock)
# Re-acquire to prove the release worked -- then release again. Holding this
# handle would make the test itself look like a running instance, and every
# app launch below would correctly refuse to start.
regrabbed = win32.acquire_single_instance()
check("lock released cleanly", regrabbed is not None)
win32.release_single_instance(regrabbed)

print("\n=== 1. first launch starts normally ===")
first = subprocess.Popen([str(PYW), str(ENTRY)], cwd=str(ROOT))
pids = wait_for_trays(1)
check("exactly one tray icon", len(pids) == 1, f"pids={pids or 'none'}")
held = win32.acquire_single_instance()
check("lock is now held by the app", held is None)
win32.release_single_instance(held)   # no-op when held is None

print("\n=== 2. second launch must NOT start another copy ===")
second = subprocess.Popen([str(PYW), str(ENTRY)], cwd=str(ROOT))
exited = None
for _ in range(20):                      # give it up to 10s to bow out
    if second.poll() is not None:
        exited = second.returncode
        break
    time.sleep(0.5)

check("second process exited by itself", exited is not None,
      f"exit code {exited}" if exited is not None else "still running")
check("second exited cleanly (code 0)", exited == 0, f"got {exited}")

time.sleep(3.0)          # a duplicate would have had time to appear by now
pids_after = tray_windows()
check("still exactly one tray icon", len(pids_after) == 1, f"pids={pids_after}")
check("it is the SAME instance", pids_after == pids, f"{pids} -> {pids_after}")

print("\n=== 3. a third and fourth launch behave the same ===")
for n in (3, 4):
    p = subprocess.Popen([str(PYW), str(ENTRY)], cwd=str(ROOT))
    for _ in range(20):
        if p.poll() is not None:
            break
        time.sleep(0.5)
    check(f"launch {n} exited instead of duplicating", p.poll() == 0, f"code {p.poll()}")
check("still one tray icon after four launches", len(tray_windows()) == 1,
      f"pids={tray_windows()}")

print("\n=== 4. shutting down releases the lock ===")
kill_app()               # kills the real process, not the launcher stub
first.terminate()
time.sleep(1.5)
freed = win32.acquire_single_instance()
check("lock free again after exit", freed is not None,
      "Windows frees the mutex with the process, even on a crash")
if freed is not None:
    win32.release_single_instance(freed)
check("no tray icons left", len(tray_windows()) == 0, f"pids={tray_windows()}")

print("\n" + ("ALL PASSED" if all(results) else f"{results.count(False)} FAILED"))
sys.exit(0 if all(results) else 1)
