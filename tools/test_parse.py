"""Parser checks against the real saved response plus degraded variants.

    .venv\\Scripts\\python.exe tools\\test_parse.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_usage import usage  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "state" / "sample_response.json"


def show(name, payload):
    snap = usage.parse(payload)
    print(f"\n=== {name} ===")
    print(f"  ok={snap.ok}  headline={snap.headline}  credits={snap.credits_label!r}")
    for limit in snap.limits:
        print(
            f"    {limit.key:<12} {limit.label:<22} {limit.percent:>5.1f}%  "
            f"resets {limit.reset_clock() or '--':<9} in {limit.countdown() or '--'}"
        )
    if not snap.limits:
        print("    (no rows)")


real = json.loads(SAMPLE.read_text(encoding="utf-8"))
show("real response", real)

# `limits` array removed -> must fall back to five_hour / seven_day.
no_limits = {k: v for k, v in real.items() if k != "limits"}
show("no `limits` array (fallback path)", no_limits)

# A future per-model cap appearing where it was null before.
with_opus = json.loads(json.dumps(real))
with_opus["limits"].append({
    "kind": "weekly_opus", "group": "weekly", "percent": 71,
    "severity": "warning", "resets_at": "2026-08-14T15:59:59+00:00", "is_active": True,
})
show("per-model weekly cap present", with_opus)

# An unknown bucket must still render rather than disappear.
unknown = json.loads(json.dumps(real))
unknown["limits"].append({
    "kind": "monthly_quantum", "group": "monthly", "percent": 12,
    "severity": "normal", "resets_at": None, "is_active": True,
})
show("unknown limit kind", unknown)

show("credits disabled", {**real, "spend": {"enabled": False}, "extra_usage": {"is_enabled": False}})
show("empty dict", {})
show("None", None)
show("garbage types", {"limits": "nope", "five_hour": 5, "spend": []})
show("wrong-shaped entries", {"limits": [None, 3, {"kind": "session"}, {"percent": 4}]})

print("\nNo exceptions raised -> parser is total.")
