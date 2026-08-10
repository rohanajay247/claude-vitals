#!/usr/bin/env python3
"""Mock-driven checks for statusline.py.

Runs the real script as a subprocess with JSON on stdin -- same path Claude Code
uses -- so we exercise the actual stdin/stdout contract, not just build().

    python statusline/test_statusline.py
"""

import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).with_name("statusline.py")
NOW = time.time()

CASES = {
    "full data": {
        "model": {"display_name": "Opus 5"},
        "effort": {"level": "high"},
        "context_window": {"used_percentage": 34.2},
        "rate_limits": {
            "five_hour": {"used_percentage": 62.5, "resets_at": int(NOW + 2 * 3600 + 41 * 60)},
            "seven_day": {"used_percentage": 88.0, "resets_at": int(NOW + 3 * 86400 + 5 * 3600)},
        },
    },
    "rate_limits absent (pre-first-response, or non-subscriber)": {
        "model": {"display_name": "Sonnet 5"},
        "effort": {"level": "medium"},
        "context_window": {"used_percentage": 12.0},
    },
    "context used_percentage null": {
        "model": {"display_name": "Opus 5"},
        "context_window": {"used_percentage": None},
        "rate_limits": {
            "five_hour": {"used_percentage": 5.0, "resets_at": int(NOW + 4 * 3600)},
            "seven_day": {"used_percentage": 20.0, "resets_at": int(NOW + 6 * 86400)},
        },
    },
    "effort absent, low usage (green)": {
        "model": {"display_name": "Haiku 4.5"},
        "context_window": {"used_percentage": 8.0},
        "rate_limits": {
            "five_hour": {"used_percentage": 15.0, "resets_at": int(NOW + 4 * 3600 + 30 * 60)},
            "seven_day": {"used_percentage": 41.0, "resets_at": int(NOW + 2 * 86400 + 12 * 3600)},
        },
    },
    "resets_at already past": {
        "model": {"display_name": "Opus 5"},
        "context_window": {"used_percentage": 50.0},
        "rate_limits": {
            "five_hour": {"used_percentage": 95.0, "resets_at": int(NOW - 900)},
            "seven_day": {"used_percentage": 99.0, "resets_at": int(NOW - 90000)},
        },
    },
    "hostile garbage (must not crash)": {
        "model": "not-a-dict",
        "context_window": {"used_percentage": "abc"},
        "rate_limits": {"five_hour": None, "seven_day": {"used_percentage": 30}},
    },
    "empty object": {},
}


def run(payload):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc


def main():
    failures = 0
    for name, payload in CASES.items():
        proc = run(payload)
        ok = proc.returncode == 0 and not proc.stderr.strip()
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"\n\033[1m[{status}] {name}\033[0m  (exit={proc.returncode})")
        for line in proc.stdout.split("\n"):
            print(f"    {line}")
        if proc.stderr.strip():
            print(f"    STDERR: {proc.stderr.strip()}")

    # Malformed stdin never reaches json.loads cleanly -- check it separately.
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="{not json at all",
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    ok = proc.returncode == 0 and not proc.stderr.strip()
    failures += 0 if ok else 1
    print(f"\n\033[1m[{'PASS' if ok else 'FAIL'}] malformed stdin\033[0m  (exit={proc.returncode})")
    print(f"    {proc.stdout}")

    print(f"\n{'All cases passed.' if not failures else str(failures) + ' case(s) FAILED.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
