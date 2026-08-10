"""Measure what Claude Vitals actually costs while running.

    .venv\\Scripts\\python.exe tools\\measure_cost.py [seconds]

Finds the running process by its own windows (not by name -- other Python
processes would confuse that) and samples CPU and memory over a window.
"""

import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
pids = set()


def _cb(hwnd, _l):
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    if "claude-vitals" in cls.value or "claude-usage" in cls.value:
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pids.add(pid.value)
    return True


user32.EnumWindows(EnumWindowsProc(_cb), 0)
if not pids:
    print("Claude Vitals does not appear to be running (no tray window found).")
    sys.exit(1)

pid = sorted(pids)[0]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
if not handle:
    print(f"Could not open pid {pid}.")
    sys.exit(1)


class FILETIME(ctypes.Structure):
    _fields_ = [("low", wt.DWORD), ("high", wt.DWORD)]

    @property
    def value(self):
        return (self.high << 32) | self.low


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def cpu_seconds():
    creation, exit_, kernel, user = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_),
                             ctypes.byref(kernel), ctypes.byref(user))
    return (kernel.value + user.value) / 1e7   # 100ns units


def working_set_mb():
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    return counters.WorkingSetSize / (1024 * 1024)


cores = ctypes.c_int()
import os
cores = os.cpu_count() or 1

print(f"Claude Vitals pid {pid}, sampling {DURATION:g}s...\n")
c0 = cpu_seconds()
time.sleep(DURATION)
c1 = cpu_seconds()

used = c1 - c0
print(f"  CPU time used     : {used:.3f} s over {DURATION:g} s wall")
print(f"  Load (one core)   : {used / DURATION * 100:.2f} %")
print(f"  Load (whole CPU)  : {used / DURATION / cores * 100:.3f} %  ({cores} cores)")
print(f"  Working set       : {working_set_mb():.1f} MB")
print("\nFor reference: a single browser tab typically uses far more of both.")
