#!/usr/bin/env python3
"""Claude Code status line.

Claude Code pipes a JSON blob to this script on stdin and renders whatever we
write to stdout. No network calls happen here -- everything comes from stdin.

Contract we rely on (all fields optional, all defensively accessed):

    model.display_name              str
    effort.level                    str   (may be absent)
    context_window.used_percentage  float (may be null)
    rate_limits.five_hour.used_percentage   float
    rate_limits.five_hour.resets_at         int, UNIX EPOCH SECONDS
    rate_limits.seven_day.used_percentage   float
    rate_limits.seven_day.resets_at         int, UNIX EPOCH SECONDS

`rate_limits` only appears for subscription accounts, and only after the first
API response of a session -- so an absent block is normal, not an error. When it
is missing we degrade to the model/context line alone.

This script must never raise and never print a traceback or error string: a
status line that shouts at you is worse than one that says little.
"""

import json
import sys
import time

# Claude Code invokes this with stdout redirected to a pipe. On Windows that
# makes Python pick the ANSI codepage (cp1252 here), which cannot encode the
# block-drawing characters below -- every render would die on UnicodeEncodeError
# and fall through to the bare fallback. Force UTF-8 before writing anything.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# --- ANSI ----------------------------------------------------------------
RESET = "\033[0m"
BOLD = "\033[1m"
GREY = "\033[38;5;245m"  # muted label grey, mirrors Claude Code's own panel
DARKGREY = "\033[38;5;238m"  # unfilled bar track
GREEN = "\033[38;5;71m"
YELLOW = "\033[38;5;179m"
RED = "\033[38;5;167m"
CYAN = "\033[38;5;74m"

BAR_WIDTH = 10
FILLED, EMPTY = "█", "░"  # full block, light shade


def colour_for(pct):
    """Green under 50, yellow to 80, red above -- same thresholds as the tray."""
    if pct is None:
        return GREY
    if pct < 50:
        return GREEN
    if pct <= 80:
        return YELLOW
    return RED


def bar(pct):
    """A fixed-width block bar, coloured by severity."""
    if pct is None:
        return f"{DARKGREY}{EMPTY * BAR_WIDTH}{RESET}"
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(pct / 100.0 * BAR_WIDTH))
    col = colour_for(pct)
    return f"{col}{FILLED * filled}{DARKGREY}{EMPTY * (BAR_WIDTH - filled)}{RESET}"


def fmt_hm(seconds):
    """`Xh Ym` for the 5-hour window."""
    m = max(0, int(seconds)) // 60
    return f"{m // 60}h {m % 60}m"


def fmt_dh(seconds):
    """`Xd Yh` for the weekly window -- minutes are noise at that scale."""
    h = max(0, int(seconds)) // 3600
    return f"{h // 24}d {h % 24}h"


def resets_in(resets_at, formatter, now):
    """Render ` · resets in ...`, or nothing if the timestamp is unusable.

    `resets_at` is epoch SECONDS. A missing, non-numeric or already-past value
    yields an empty string rather than a bogus countdown.
    """
    try:
        remaining = float(resets_at) - now
    except (TypeError, ValueError):
        return ""
    if remaining <= 0:
        return ""
    return f" {GREY}· resets in {formatter(remaining)}{RESET}"


def dig(obj, *path):
    """Walk nested dicts, returning None the moment anything isn't there."""
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def as_pct(value):
    """Coerce to float, tolerating null/absent/garbage."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def build(data, now=None):
    """Render the two status lines. Pure function -- easy to test with mocks."""
    now = time.time() if now is None else now
    lines = []

    # --- line 1: model / effort / context -------------------------------
    model = dig(data, "model", "display_name") or "Claude"
    left = [f"{CYAN}{BOLD}{model}{RESET}"]

    effort = dig(data, "effort", "level")
    if effort:
        left.append(f"{GREY}{effort}{RESET}")

    ctx = as_pct(dig(data, "context_window", "used_percentage"))
    if ctx is not None:
        left.append(f"{GREY}ctx{RESET} {bar(ctx)} {colour_for(ctx)}{ctx:.0f}%{RESET}")
    else:
        # Context is genuinely unknown early in a session; say so quietly
        # rather than printing a misleading 0%.
        left.append(f"{GREY}ctx {EMPTY * BAR_WIDTH} --{RESET}")

    lines.append(f" {GREY}│{RESET} ".join(left))

    # --- line 2: rate limits (subscribers only, post-first-response) -----
    limits = dig(data, "rate_limits")
    if not isinstance(limits, dict):
        return lines

    parts = []

    five = as_pct(dig(limits, "five_hour", "used_percentage"))
    if five is not None:
        parts.append(
            f"{GREY}Session:{RESET} {bar(five)} {colour_for(five)}{five:.0f}%{RESET}"
            + resets_in(dig(limits, "five_hour", "resets_at"), fmt_hm, now)
        )

    week = as_pct(dig(limits, "seven_day", "used_percentage"))
    if week is not None:
        parts.append(
            f"{GREY}Weekly:{RESET} {bar(week)} {colour_for(week)}{week:.0f}%{RESET}"
            + resets_in(dig(limits, "seven_day", "resets_at"), fmt_dh, now)
        )

    if parts:
        lines.append(f"  {GREY}│{RESET}  ".join(parts))

    return lines


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            data = {}
        sys.stdout.write("\n".join(build(data)))
    except Exception:
        # Absolute last resort. A status line is decoration; if anything at all
        # goes wrong we print a neutral token and exit clean so Claude Code
        # never surfaces a stack trace where the model name should be.
        try:
            sys.stdout.write(f"{CYAN}Claude{RESET}")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
